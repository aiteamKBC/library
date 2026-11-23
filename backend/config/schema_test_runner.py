"""Synthetic model tables with NO migration execution or application DB access."""
from unittest import skip
from django.apps import apps
from django.conf import settings
from django.core.management.sql import emit_post_migrate_signal
from django.db import connections
from django.test.runner import DiscoverRunner


class SchemaOnlyRunner(DiscoverRunner):
    def build_suite(self, *args, **kwargs):
        suite = super().build_suite(*args, **kwargs)

        def exclude_migration_tests(items):
            for item in items:
                if hasattr(item, "_testMethodName"):
                    cls = type(item)
                    if cls.__module__ == "library.test_phase2" and cls.__name__ == "Phase2MigrationTests":
                        skip("Migration execution is forbidden in this schema-only test run.")(cls)
                else:
                    exclude_migration_tests(item)
        exclude_migration_tests(suite)
        return suite

    def setup_databases(self, **kwargs):
        conn = connections["default"]
        cfg = conn.settings_dict
        if settings.LIBRARY_ISOLATED_TESTS and conn.vendor == "sqlite" and cfg["NAME"] == ":memory:":
            if conn.introspection.table_names():
                raise RuntimeError("Refusing to reuse existing synthetic tables.")
            with conn.schema_editor() as editor:
                for model in apps.get_models():
                    if model._meta.managed and not model._meta.proxy:
                        editor.create_model(model)
            emit_post_migrate_signal(verbosity=0, interactive=False, db="default")
            self.log("In-memory model tables only; PostgreSQL concurrency is NOT verified.")
            return []
        if (not settings.LIBRARY_ISOLATED_TESTS or conn.vendor != "postgresql"
                or cfg["HOST"] != "127.0.0.1" or cfg["USER"] != "kbc_test_admin"
                or cfg["NAME"] != "kbc_phase3_tests" or cfg["TEST"]["NAME"] != "test_kbc_phase3_tests"):
            raise RuntimeError("Schema-only runner requires the guarded fresh synthetic PostgreSQL cluster.")
        original_name = cfg["NAME"]
        # Only CREATE DATABASE in the fresh cluster, not create_test_db(), whose
        # default implementation would execute Django's migrate command.
        conn.creation._create_test_db(self.verbosity, autoclobber=False, keepdb=False)
        conn.close()
        cfg["NAME"] = cfg["TEST"]["NAME"]
        settings.DATABASES["default"]["NAME"] = cfg["NAME"]
        if conn.introspection.table_names():
            raise RuntimeError("Refusing to reuse any existing tables in schema-only tests.")
        with conn.schema_editor() as editor:
            for model in apps.get_models():
                if model._meta.managed and not model._meta.proxy:
                    editor.create_model(model)
        # Synthetic auth/content-type seed data only; no migration executor.
        emit_post_migrate_signal(verbosity=0, interactive=False, db="default")
        self.log("Synthetic PostgreSQL tables created directly from models; migrations disabled.")
        return [(conn, original_name, True)]
