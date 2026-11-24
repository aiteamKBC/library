from unittest.mock import patch

import psycopg
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient

from .student_auth import fetch_allowlisted_student
from .models import BookCopy, Category, Loan, Resource, ensure_user_profile


DIRECTORY = {
    "KBC_LEARNERS_DATABASE_URL": "postgresql://synthetic:secret@directory.invalid/synthetic",
    "KBC_LEARNERS_SCHEMA": "Learner", "KBC_LEARNERS_TABLE": "learners",
    "KBC_LEARNERS_EMAIL_COLUMN": "email", "KBC_LEARNERS_NAME_COLUMN": "full_name",
    "KBC_ALLOWLIST_DATABASE_URL": "postgresql://legacy.invalid/never-used",
}


@override_settings(**DIRECTORY)
class LearnerDirectoryLookupTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        mock = patch("library.student_auth.psycopg.connect")
        self.connect = mock.start()
        self.addCleanup(mock.stop)
        self.cursor = self.connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
        self.cursor.fetchone.return_value = (" Synthetic Learner ", " Student@Example.test ")

    def test_reads_new_directory_in_read_only_transaction_with_normalized_email(self):
        result = fetch_allowlisted_student(" STUDENT@example.test ")
        self.assertEqual((result.email, result.full_name), ("student@example.test", "Synthetic Learner"))
        self.connect.assert_called_once_with(DIRECTORY["KBC_LEARNERS_DATABASE_URL"], connect_timeout=5)
        calls = self.cursor.execute.call_args_list
        self.assertEqual(calls[0].args, ("SET TRANSACTION READ ONLY",))
        self.assertEqual(calls[1].args, ("SET LOCAL statement_timeout = '5s'",))
        self.assertIn('from "Learner"."learners"', calls[2].args[0].as_string())
        self.assertIn('select "full_name", "email"', calls[2].args[0].as_string())
        self.assertEqual(calls[2].args[1], ["student@example.test"])

    def test_positive_cache_reuses_normalized_lookup(self):
        first = fetch_allowlisted_student("STUDENT@example.test")
        self.assertEqual(fetch_allowlisted_student(" student@example.test "), first)
        self.connect.assert_called_once()

    def test_missing_learner_is_cached_without_old_source_fallback(self):
        self.cursor.fetchone.return_value = None
        self.assertIsNone(fetch_allowlisted_student("unknown@example.test"))
        self.assertIsNone(fetch_allowlisted_student("unknown@example.test"))
        self.connect.assert_called_once_with(DIRECTORY["KBC_LEARNERS_DATABASE_URL"], connect_timeout=5)

    def test_legacy_cached_admission_cannot_grant_access(self):
        cache.set("library:allowlist:student@example.test", {"email": "student@example.test", "full_name": "Old Learner"})
        self.cursor.fetchone.return_value = None
        self.assertIsNone(fetch_allowlisted_student("student@example.test"))
        self.connect.assert_called_once()

    def test_directory_change_cannot_reuse_previous_admission(self):
        fetch_allowlisted_student("student@example.test")
        self.cursor.fetchone.return_value = None
        with override_settings(KBC_LEARNERS_DATABASE_URL="postgresql://other.invalid/synthetic"):
            self.assertIsNone(fetch_allowlisted_student("student@example.test"))
        self.assertEqual(self.connect.call_count, 2)

    def test_missing_new_configuration_never_uses_legacy_database_or_cache(self):
        fetch_allowlisted_student("student@example.test")
        self.connect.reset_mock()
        with override_settings(KBC_LEARNERS_DATABASE_URL=""), self.assertRaises(RuntimeError):
            fetch_allowlisted_student("student@example.test")
        self.connect.assert_not_called()

    def test_connection_failure_is_sanitized_and_not_cached_as_rejection(self):
        self.connect.side_effect = psycopg.OperationalError("synthetic secret should not escape")
        with self.assertRaisesRegex(RuntimeError, "directory is unavailable") as caught:
            fetch_allowlisted_student("student@example.test")
        self.assertNotIn("secret", str(caught.exception))
        self.connect.side_effect = None
        self.assertIsNotNone(fetch_allowlisted_student("student@example.test"))

    def test_email_is_bound_as_parameter(self):
        email = "x' OR TRUE --@example.test"
        fetch_allowlisted_student(email)
        query, params = self.cursor.execute.call_args.args
        self.assertNotIn(email, query.as_string())
        self.assertEqual(params, [email.lower()])

    def test_empty_email_does_not_connect(self):
        self.assertIsNone(fetch_allowlisted_student(" "))
        self.connect.assert_not_called()


@override_settings(**DIRECTORY)
class LearnerDirectoryLoginTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.client = APIClient()
        mock = patch("library.student_auth.psycopg.connect")
        self.connect = mock.start()
        self.addCleanup(mock.stop)
        self.cursor = self.connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
        self.cursor.fetchone.return_value = ("New Learner", "learner@example.test")

    def login(self):
        return self.client.post("/api/auth/student-login/", {"email": "learner@example.test"}, format="json")

    def test_new_learner_gets_library_account_from_new_source(self):
        response = self.login()
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data["token"])
        user = get_user_model().objects.get(email="learner@example.test")
        self.assertEqual(user.get_full_name(), "New Learner")
        self.assertEqual(ensure_user_profile(user).role, "student")

    def test_existing_account_and_loan_identity_are_preserved(self):
        user = get_user_model().objects.create_user("existing", email="learner@example.test", first_name="Old")
        category = Category.objects.create(name="Synthetic", slug="synthetic")
        book = Resource.objects.create(id="directory-book", title="Synthetic", author="Author", category=category)
        copy = BookCopy.objects.create(resource=book, accession_number="DIRECTORY-1")
        loan = Loan.objects.create(id="directory-loan", borrower=user, borrower_email=user.email,
                                   borrower_name="Old", book_copy=copy)
        response = self.login()
        self.assertEqual(response.status_code, 200, response.data)
        user.refresh_from_db()
        loan.refresh_from_db()
        self.assertEqual(user.get_full_name(), "New Learner")
        self.assertEqual(loan.borrower_id, user.pk)
        self.assertEqual(get_user_model().objects.filter(email=user.email).count(), 1)

    def test_old_local_account_alone_does_not_grant_access(self):
        get_user_model().objects.create_user("existing", email="learner@example.test")
        self.cursor.fetchone.return_value = None
        self.assertEqual(self.login().status_code, 400)

    def test_staff_account_cannot_be_converted_into_student(self):
        user = get_user_model().objects.create_user("staff", email="learner@example.test", is_staff=True)
        self.assertEqual(self.login().status_code, 400)
        user.refresh_from_db()
        self.assertTrue(user.is_staff)

    def test_directory_outage_returns_safe_error_without_creating_account(self):
        self.connect.side_effect = psycopg.OperationalError("synthetic secret should not escape")
        response = self.login()
        self.assertEqual(response.status_code, 400)
        self.assertIn("temporarily unavailable", str(response.data))
        self.assertNotIn("secret", str(response.data))
        self.assertFalse(get_user_model().objects.filter(email="learner@example.test").exists())
