from django.contrib.auth import get_user_model
import os
import uuid
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.db.models import Q
from django.utils import timezone

from .timezones import (
    confirmation_timezone, london_today, calculate_deadline, LONDON,
    validated_timezone, validate_iana_timezone, approved_utc_cutover, require_aware,
)


User = get_user_model()


def loan_return_evidence_upload_to(instance: "Loan", filename: str) -> str:
    extension = os.path.splitext(filename or "")[1].lower()
    if not extension:
        extension = ".bin"
    return f"loan-return-evidence/{instance.id}/{uuid.uuid4().hex}{extension}"


class UserProfile(models.Model):
    class Role(models.TextChoices):
        STUDENT = "student", "Student"
        LIBRARIAN = "librarian", "Librarian"
        ADMIN = "admin", "Admin"

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="library_profile")
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.STUDENT)
    phone_number = models.CharField(max_length=30, blank=True)
    student_id_code = models.CharField(max_length=40, blank=True)
    time_zone = models.CharField(max_length=100, null=True, blank=True, validators=[validate_iana_timezone])
    time_zone_source = models.CharField(max_length=10, choices=[("browser", "Browser"), ("manual", "Explicit choice")], blank=True)
    time_zone_updated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["user__username"]
        constraints = [models.CheckConstraint(
            condition=(Q(time_zone__isnull=True, time_zone_source="", time_zone_updated_at__isnull=True)
                       | (Q(time_zone__isnull=False, time_zone_source__in=["browser", "manual"], time_zone_updated_at__isnull=False) & ~Q(time_zone=""))),
            name="lib_profile_timezone_complete",
        )]

    def __str__(self) -> str:
        return f"{self.user.get_username()} ({self.role})"

    @property
    def is_staff_role(self) -> bool:
        return self.role in {self.Role.LIBRARIAN, self.Role.ADMIN}


class Category(models.Model):
    name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=140, unique=True)
    description = models.TextField(blank=True)
    color = models.CharField(max_length=20, default="#442F73")
    icon = models.CharField(max_length=50, default="ri-book-open-line")

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "categories"

    def __str__(self) -> str:
        return self.name


class Resource(models.Model):
    DEFAULT_COPY_COUNT = 3

    class ResourceType(models.TextChoices):
        BOOK = "Book", "Book"
        ARTICLE = "Article", "Article"
        GUIDE = "Guide", "Guide"
        JOURNAL = "Journal", "Journal"
        VIDEO = "Video", "Video"
        TEMPLATE = "Template", "Template"

    id = models.CharField(primary_key=True, max_length=50)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="resources")
    type = models.CharField(max_length=20, choices=ResourceType.choices, default=ResourceType.BOOK)
    level = models.CharField(max_length=50, blank=True)
    author = models.CharField(max_length=255)
    publisher = models.CharField(max_length=255, blank=True)
    edition = models.CharField(max_length=80, blank=True)
    publication_year = models.CharField(max_length=4, blank=True)
    page_count = models.PositiveIntegerField(blank=True, null=True)
    isbn13 = models.CharField(max_length=13, blank=True)
    isbn10 = models.CharField(max_length=10, blank=True)
    cover_image = models.URLField(blank=True)
    info_link = models.URLField(blank=True)
    date_added = models.DateField(default=timezone.localdate)
    featured = models.BooleanField(default=False)
    popular = models.BooleanField(default=False)
    cover_color = models.CharField(max_length=20, default="#442F73")

    class Meta:
        ordering = ["-date_added", "title"]

    def __str__(self) -> str:
        return self.title

    def _prefetched_copies(self):
        prefetched = getattr(self, "_prefetched_objects_cache", {})
        return prefetched.get("copies")

    def _copies_for_metrics(self):
        return self._prefetched_copies() or list(self.copies.all())

    def _shelf_available_copies(self) -> int:
        return sum(1 for copy in self._copies_for_metrics() if copy.status == BookCopy.CopyStatus.AVAILABLE)

    @property
    def pending_borrow_request_count(self) -> int:
        annotated = getattr(self, "pending_borrow_request_total", None)
        if annotated is not None:
            return int(annotated)
        return Loan.objects.filter(
            book_copy__resource=self,
            status=Loan.LoanStatus.REQUESTED,
            loan_type=Loan.LoanType.BORROW,
        ).count()

    @property
    def borrowable_copies(self) -> int:
        return max(self._shelf_available_copies() - self.pending_borrow_request_count, 0)

    @property
    def queue_full(self) -> bool:
        shelf_available = self._shelf_available_copies()
        return shelf_available > 0 and self.pending_borrow_request_count >= shelf_available

    @property
    def pending_requests_cover_available_copies(self) -> bool:
        return self.queue_full

    def ensure_copy_inventory(self, target_count: int | None = None):
        target_count = self.DEFAULT_COPY_COUNT if target_count is None else target_count
        existing_accessions = set(self.copies.values_list("accession_number", flat=True))
        copies_to_create: list[BookCopy] = []

        for number in range(1, target_count + 1):
            accession_number = f"{self.id}-{number:03d}"
            if accession_number in existing_accessions:
                continue
            copies_to_create.append(BookCopy(resource=self, accession_number=accession_number))

        if copies_to_create:
            BookCopy.objects.bulk_create(copies_to_create)

        return copies_to_create

    def sync_copy_inventory(self, target_count: int | None = None):
        target_count = self.DEFAULT_COPY_COUNT if target_count is None else target_count
        if target_count < 1:
            raise ValidationError("A library title must keep at least 1 copy.")

        copies = list(self.copies.order_by("-accession_number").prefetch_related("loans"))
        current_count = len(copies)

        if target_count == current_count:
            return {"created": 0, "removed": 0}

        if target_count > current_count:
            created = self.ensure_copy_inventory(target_count)
            return {"created": len(created), "removed": 0}

        copies_to_remove = current_count - target_count
        removable_copies = [
            copy
            for copy in copies
            if copy.status == BookCopy.CopyStatus.AVAILABLE and not copy.loans.exists()
        ]

        if len(removable_copies) < copies_to_remove:
            raise ValidationError(
                "This title cannot be reduced to that count yet because not enough unused available copies can be removed safely."
            )

        for copy in removable_copies[:copies_to_remove]:
            copy.delete()

        return {"created": 0, "removed": copies_to_remove}

    def first_available_copy(self):
        prefetched_copies = self._prefetched_copies()
        if prefetched_copies is not None:
            ordered = sorted(prefetched_copies, key=lambda copy: copy.accession_number)
            return next((copy for copy in ordered if copy.status == BookCopy.CopyStatus.AVAILABLE), None)
        return self.copies.filter(status=BookCopy.CopyStatus.AVAILABLE).order_by("accession_number").first()

    def first_usable_copy(self):
        blocked_statuses = {BookCopy.CopyStatus.LOST, BookCopy.CopyStatus.MAINTENANCE}
        prefetched_copies = self._prefetched_copies()
        if prefetched_copies is not None:
            ordered = sorted(prefetched_copies, key=lambda copy: copy.accession_number)
            return next((copy for copy in ordered if copy.status not in blocked_statuses), None)
        return self.copies.exclude(status__in=blocked_statuses).order_by("accession_number").first()

    def _active_circulation_loans(self):
        copies = self._prefetched_copies()
        if copies is not None:
            active_loans: list[Loan] = []
            for copy in copies:
                copy_prefetched = getattr(copy, "_prefetched_objects_cache", {})
                prefetched_loans = copy_prefetched.get("loans")
                if prefetched_loans is None:
                    return list(
                        Loan.objects.filter(
                            book_copy__resource=self,
                            status__in=Loan.circulation_statuses(),
                            due_date__isnull=False,
                        ).order_by("due_date")
                    )
                active_loans.extend(
                    loan
                    for loan in prefetched_loans
                    if loan.status in Loan.circulation_statuses() and loan.due_date is not None
                )
            return sorted(active_loans, key=lambda loan: loan.due_date)
        return list(
            Loan.objects.filter(
                book_copy__resource=self,
                status__in=Loan.circulation_statuses(),
                due_date__isnull=False,
            ).order_by("due_date")
        )

    @property
    def total_copies(self) -> int:
        return len(self._copies_for_metrics())

    @property
    def available_copies(self) -> int:
        return self._shelf_available_copies()

    @property
    def availability_status(self) -> str:
        statuses = [copy.status for copy in self._copies_for_metrics()]
        if not statuses:
            return BookCopy.CopyStatus.LOST
        if self.available_copies > 0:
            return BookCopy.CopyStatus.AVAILABLE
        if BookCopy.CopyStatus.RESERVED in statuses:
            return BookCopy.CopyStatus.RESERVED
        if BookCopy.CopyStatus.BORROWED in statuses:
            return BookCopy.CopyStatus.BORROWED
        if BookCopy.CopyStatus.MAINTENANCE in statuses:
            return BookCopy.CopyStatus.MAINTENANCE
        return BookCopy.CopyStatus.LOST

    @property
    def availability_label(self) -> str:
        if self.queue_full:
            return "Queue full"
        if self.borrowable_copies > 0 and self.pending_borrow_request_count > 0:
            return f"{self.borrowable_copies} open to borrow"
        if self.available_copies > 0:
            return f"{self.available_copies} available"

        labels = {
            BookCopy.CopyStatus.AVAILABLE: "Available now",
            BookCopy.CopyStatus.RESERVED: "Reserved",
            BookCopy.CopyStatus.BORROWED: "Unavailable",
            BookCopy.CopyStatus.LOST: "Unavailable",
            BookCopy.CopyStatus.MAINTENANCE: "Unavailable",
        }
        return labels.get(self.availability_status, "Unavailable")

    @property
    def can_borrow(self) -> bool:
        return self.borrowable_copies > 0

    @property
    def can_reserve(self) -> bool:
        return self.availability_status == BookCopy.CopyStatus.BORROWED

    @property
    def expected_available_date(self):
        active_loans = self._active_circulation_loans()
        due_dates = [loan.due_date for loan in active_loans if loan.due_date is not None]
        return min(due_dates) if due_dates else None

    @property
    def availability_note(self) -> str:
        if self.queue_full:
            return "All copies currently on the shelf are already covered by pending borrow requests. Where shown, the expected date reflects the earliest current due date for a borrowed copy and does not guarantee immediate availability."
        if self.availability_status == BookCopy.CopyStatus.BORROWED:
            # expected_available_date is surfaced separately in the UI — do not repeat it here.
            return "No copies are currently available. Where shown, the expected date reflects the earliest current due date for a borrowed copy and may change if the item is returned late."
        if self.availability_status == BookCopy.CopyStatus.RESERVED:
            return "No copies are currently available. Register below and we will let you know when one becomes free."
        if self.availability_status == BookCopy.CopyStatus.AVAILABLE:
            return ""
        return "Please contact the library team for availability updates."

    @property
    def feedback_count(self) -> int:
        annotated = getattr(self, "feedback_total", None)
        if annotated is not None:
            return int(annotated)
        return self.feedback_entries.count()

    @property
    def feedback_average_rating(self) -> float | None:
        annotated = getattr(self, "feedback_average_rating_value", None)
        if annotated is not None:
            return float(annotated) if annotated is not None else None
        aggregate = self.feedback_entries.aggregate(models.Avg("star_rating"))
        value = aggregate.get("star_rating__avg")
        return float(value) if value is not None else None

    @property
    def feedback_recommend_count(self) -> int:
        annotated = getattr(self, "feedback_recommend_total", None)
        if annotated is not None:
            return int(annotated)
        return self.feedback_entries.filter(
            would_recommend=BookFeedback.RecommendChoice.YES,
        ).count()

    @property
    def feedback_learned_count(self) -> int:
        annotated = getattr(self, "feedback_learned_total", None)
        if annotated is not None:
            return int(annotated)
        return self.feedback_entries.filter(
            learned_something__in=(
                BookFeedback.LearnedChoice.YES,
                BookFeedback.LearnedChoice.SOMEWHAT,
            ),
        ).count()

    @property
    def feedback_recommend_rate(self) -> int:
        total = self.feedback_count
        if total <= 0:
            return 0
        return round((self.feedback_recommend_count / total) * 100)

    @property
    def feedback_learned_rate(self) -> int:
        total = self.feedback_count
        if total <= 0:
            return 0
        return round((self.feedback_learned_count / total) * 100)


class BookCopy(models.Model):
    class CopyStatus(models.TextChoices):
        AVAILABLE = "available", "Available"
        RESERVED = "reserved", "Reserved"
        BORROWED = "borrowed", "Borrowed"
        LOST = "lost", "Lost"
        MAINTENANCE = "maintenance", "Maintenance"

    resource = models.ForeignKey(Resource, on_delete=models.CASCADE, related_name="copies")
    accession_number = models.CharField(max_length=50, unique=True, blank=True)
    status = models.CharField(max_length=20, choices=CopyStatus.choices, default=CopyStatus.AVAILABLE)
    shelf_location = models.CharField(max_length=120, blank=True)
    notes = models.TextField(blank=True)
    added_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["resource__title", "accession_number"]

    def __str__(self) -> str:
        return f"{self.resource.title} ({self.accession_number})"

    def save(self, *args, **kwargs):
        if not self.accession_number:
            existing_accessions = set(
                self.resource.copies.exclude(pk=self.pk).values_list("accession_number", flat=True)
            )
            next_number = 1
            while f"{self.resource_id}-{next_number:03d}" in existing_accessions:
                next_number += 1
            self.accession_number = f"{self.resource_id}-{next_number:03d}"
        super().save(*args, **kwargs)


class LoanQuerySet(models.QuerySet):
    PROTECTED_FIELDS = {"due_date", "delivery_days", "status", "approved_at", "borrowed_at", "email_deadline_revision",
                        "calculation_policy", "calculation_timezone", "operational_timezone", "confirmation_local_date"}

    def update(self, **kwargs):
        if self.PROTECTED_FIELDS.intersection(kwargs):
            raise ValidationError("Use Loan.save() for deadline/state changes; bulk updates bypass policy and revision protection.")
        return super().update(**kwargs)

    def bulk_update(self, objs, fields, **kwargs):
        if self.PROTECTED_FIELDS.intersection(fields):
            raise ValidationError("Use Loan.save() for deadline/state changes.")
        return super().bulk_update(objs, fields, **kwargs)

    def bulk_create(self, objs, **kwargs):
        raise ValidationError("Create loans individually so confirmation policy and revisions are validated.")


class Loan(models.Model):
    objects = models.Manager.from_queryset(LoanQuerySet)()
    BORROWING_DAYS = 30
    POLICY_FIELDS = ("calculation_policy", "calculation_timezone", "operational_timezone", "confirmation_local_date")

    class LoanStatus(models.TextChoices):
        REQUESTED = "requested", "Requested"
        RESERVED = "reserved", "Reserved"
        APPROVED = "approved", "Approved"
        BORROWED = "borrowed", "Borrowed"
        RETURNED = "returned", "Returned"
        NOTIFY = "notify", "Notify"
        OVERDUE = "overdue", "Overdue"
        CANCELLED = "cancelled", "Cancelled"

    class LoanType(models.TextChoices):
        BORROW = "borrow", "Borrow Request"
        NOTIFY = "notify", "Notification Registration"

    class ReturnCondition(models.TextChoices):
        GOOD = "good", "Good"
        WORN = "worn", "Worn / Used"
        DAMAGED = "damaged", "Damaged"
        TORN = "torn", "Needs Repair"

    id = models.CharField(primary_key=True, max_length=50)
    borrower = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="library_loans",
        blank=True,
        null=True,
    )
    borrower_name = models.CharField(max_length=120, blank=True)
    borrower_email = models.EmailField(blank=True)
    borrower_phone = models.CharField(max_length=30, blank=True)
    borrower_student_id = models.CharField(max_length=40, blank=True)
    book_copy = models.ForeignKey(BookCopy, on_delete=models.PROTECT, related_name="loans")
    status = models.CharField(max_length=20, choices=LoanStatus.choices, default=LoanStatus.REQUESTED)
    loan_type = models.CharField(max_length=10, choices=LoanType.choices, default=LoanType.BORROW)
    requested_at = models.DateTimeField(default=timezone.now)
    requested_from = models.DateField(blank=True, null=True)
    approved_at = models.DateTimeField(blank=True, null=True)
    borrowed_at = models.DateTimeField(blank=True, null=True)
    due_date = models.DateField(blank=True, null=True)
    delivery_days = models.PositiveSmallIntegerField(default=0)
    calculation_policy = models.CharField(max_length=20, null=True, blank=True,
        choices=[("cairo_v1", "Historical Cairo"), ("london_v1", "London"), ("user_local_v1", "Student local")], editable=False)
    calculation_timezone = models.CharField(max_length=100, null=True, blank=True, validators=[validate_iana_timezone], editable=False)
    operational_timezone = models.CharField(max_length=100, null=True, blank=True, validators=[validate_iana_timezone], editable=False)
    confirmation_local_date = models.DateField(null=True, blank=True, editable=False)
    email_deadline_revision = models.PositiveBigIntegerField(default=0, editable=False)
    returned_at = models.DateTimeField(blank=True, null=True)
    return_condition = models.CharField(max_length=20, choices=ReturnCondition.choices, blank=True)
    return_condition_notes = models.TextField(blank=True)
    return_evidence = models.FileField(upload_to=loan_return_evidence_upload_to, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="approved_library_loans",
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-requested_at"]
        constraints = [models.CheckConstraint(
            condition=(Q(calculation_policy__isnull=True, calculation_timezone__isnull=True, operational_timezone__isnull=True, confirmation_local_date__isnull=True)
                       | (Q(calculation_policy__isnull=False, calculation_policy__in=["cairo_v1", "london_v1", "user_local_v1"], calculation_timezone__isnull=False, operational_timezone__isnull=False, confirmation_local_date__isnull=False)
                          & ~Q(calculation_timezone="") & ~Q(operational_timezone=""))),
            name="lib_loan_policy_complete",
        ), models.CheckConstraint(
            condition=(
                (~Q(calculation_policy="cairo_v1") | Q(calculation_timezone="Africa/Cairo"))
                & (~Q(calculation_policy="london_v1") | Q(calculation_timezone="Europe/London"))
                & (~Q(calculation_policy="user_local_v1") | Q(operational_timezone=models.F("calculation_timezone")))
            ), name="lib_loan_policy_zones",
        )]

    def __str__(self) -> str:
        return f"{self.book_copy.accession_number} - {self.borrower}"

    @classmethod
    def active_statuses(cls) -> tuple[str, ...]:
        return (
            cls.LoanStatus.REQUESTED,
            cls.LoanStatus.RESERVED,
            cls.LoanStatus.APPROVED,
            cls.LoanStatus.BORROWED,
            cls.LoanStatus.OVERDUE,
        )

    @classmethod
    def circulation_statuses(cls) -> tuple[str, ...]:
        return (
            cls.LoanStatus.BORROWED,
            cls.LoanStatus.OVERDUE,
        )

    @classmethod
    def pre_checkout_statuses(cls) -> tuple[str, ...]:
        return (
            cls.LoanStatus.APPROVED,
        )

    @classmethod
    def terminal_statuses(cls) -> tuple[str, ...]:
        return (
            cls.LoanStatus.RETURNED,
            cls.LoanStatus.NOTIFY,
            cls.LoanStatus.CANCELLED,
        )

    @classmethod
    def allowed_status_transitions(cls) -> dict[str, set[str]]:
        return {
            cls.LoanStatus.REQUESTED: {
                cls.LoanStatus.APPROVED,
                cls.LoanStatus.BORROWED,
                cls.LoanStatus.NOTIFY,
                cls.LoanStatus.CANCELLED,
            },
            cls.LoanStatus.APPROVED: {
                cls.LoanStatus.BORROWED,
                cls.LoanStatus.CANCELLED,
            },
            cls.LoanStatus.RESERVED: {
                cls.LoanStatus.BORROWED,
                cls.LoanStatus.CANCELLED,
            },
            cls.LoanStatus.BORROWED: {
                cls.LoanStatus.RETURNED,
                cls.LoanStatus.OVERDUE,
            },
            cls.LoanStatus.OVERDUE: {
                cls.LoanStatus.RETURNED,
            },
            cls.LoanStatus.RETURNED: set(),
            cls.LoanStatus.NOTIFY: set(),
            cls.LoanStatus.CANCELLED: set(),
        }

    def clean(self):
        super().clean()
        previous = None
        if not self.borrower_id and not (self.borrower_name and self.borrower_email):
            raise ValidationError("A loan must include either a linked borrower or a borrower name and email.")

        if self.pk:
            previous_values = Loan.objects.filter(pk=self.pk).values(
                "status", "delivery_days", "approved_at", "borrowed_at", "due_date",
                *self.POLICY_FIELDS,
            ).first()
            previous = previous_values["status"] if previous_values else None
            if previous_values:
                self.validate_confirmation_history(previous_values)
                self.validate_policy_history(previous_values)
            first_confirmation = self.status in {self.LoanStatus.APPROVED, self.LoanStatus.BORROWED} and (
                previous is None or previous in {self.LoanStatus.REQUESTED, self.LoanStatus.RESERVED}
            )
            delivery_changed = previous_values and previous_values["delivery_days"] != self.delivery_days
            if first_confirmation:
                self.first_confirmation_policy(self.approved_at or timezone.now())
            elif delivery_changed and (self.approved_at or self.borrowed_at or previous not in {
                self.LoanStatus.REQUESTED, self.LoanStatus.RESERVED, self.LoanStatus.NOTIFY,
            }):
                self.calculate_due_date()
            if previous and previous != self.status:
                allowed = self.allowed_status_transitions().get(previous, set())
                # A corrected delivery period can make an overdue loan current again.
                delivery_corrected = (
                    previous == self.LoanStatus.OVERDUE
                    and self.status == self.LoanStatus.BORROWED
                    and self.delivery_days != previous_values["delivery_days"]
                    and self.due_date is not None
                    and self.due_date >= self.calendar_today()
                )
                if self.status not in allowed and not delivery_corrected:
                    raise ValidationError({"status": f"Cannot change loan status from {previous} to {self.status}."})

        if self.status == self.LoanStatus.RETURNED and previous != self.LoanStatus.RETURNED and not self.return_condition:
            raise ValidationError({"return_condition": "Please record the condition of the returned book copy."})

        if (
            self.status == self.LoanStatus.RETURNED
            and previous != self.LoanStatus.RETURNED
            and self.return_condition in {self.ReturnCondition.DAMAGED, self.ReturnCondition.TORN}
            and not self.return_evidence
        ):
            raise ValidationError(
                {"return_evidence": "Please attach photo or PDF evidence for damaged or repair-needed returns."}
            )

        if not self.book_copy_id or self.status not in self.active_statuses():
            return

        conflicting_for_resource = Loan.objects.filter(
            book_copy__resource=self.book_copy.resource,
            status__in=self.active_statuses(),
        )
        if self.pk:
            conflicting_for_resource = conflicting_for_resource.exclude(pk=self.pk)

        conflicting_for_copy = conflicting_for_resource.filter(book_copy=self.book_copy)

        same_borrower_filter = Q()
        if self.borrower_id:
            same_borrower_filter = Q(borrower_id=self.borrower_id)
        elif self.borrower_email:
            same_borrower_filter = Q(borrower_email__iexact=self.borrower_email)
        elif self.borrower_name and self.borrower_phone:
            same_borrower_filter = Q(
                borrower_name__iexact=self.borrower_name,
                borrower_phone=self.borrower_phone,
            )

        if same_borrower_filter and conflicting_for_resource.filter(same_borrower_filter).exists():
            raise ValidationError({"book_copy": "You already have an active borrow or reservation request for this book."})

        if self.status == self.LoanStatus.RESERVED:
            if conflicting_for_copy.filter(status=self.LoanStatus.RESERVED).exists():
                raise ValidationError({"book_copy": "This copy already has an active reservation."})
            if conflicting_for_copy.filter(status__in=self.pre_checkout_statuses()).exists():
                raise ValidationError({"book_copy": "This copy is already being prepared for another borrower."})
        elif self.status == self.LoanStatus.REQUESTED:
            # Keep the waiting-list behaviour simple: multiple students can
            # submit borrow requests for the same resource and the librarian
            # later confirms one of them. We only block duplicate requests from
            # the same borrower (handled above).
            return
        else:
            if conflicting_for_copy.filter(status=self.LoanStatus.RESERVED).exists():
                raise ValidationError({"book_copy": "This copy is reserved for another student."})
            if conflicting_for_copy.filter(status__in=(*self.pre_checkout_statuses(), *self.circulation_statuses())).exists():
                raise ValidationError({"book_copy": "This copy already has an active borrowing flow."})

    def save(self, *args, **kwargs):
        # Preserve Django's legacy positional save arguments while ensuring that
        # automatic deadline/revision fields join the actual update_fields set.
        if len(args) > 4:
            raise TypeError("Loan.save() accepts at most four positional save options.")
        for name, value in zip(("force_insert", "force_update", "using", "update_fields"), args):
            if name in kwargs:
                raise TypeError(f"Loan.save() received duplicate {name}.")
            kwargs[name] = value
        args = ()
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            update_fields = set(update_fields)
            if not update_fields:
                return
        with transaction.atomic():
            previous = Loan.objects.select_for_update().filter(pk=self.pk).first() if self.pk else None
            if previous:
                self.validate_confirmation_history({
                    field: getattr(previous, field) for field in ("status", "approved_at", "borrowed_at")
                })
                self.validate_policy_history({"status": previous.status, **{
                    field: getattr(previous, field) for field in self.POLICY_FIELDS
                }})
                effective_due = self.due_date if update_fields is None or "due_date" in update_fields else previous.due_date
                effective_days = self.delivery_days if update_fields is None or "delivery_days" in update_fields else previous.delivery_days
                if self.email_deadline_revision != previous.email_deadline_revision and (
                    effective_due != previous.due_date or effective_days != previous.delivery_days
                ):
                    raise ValidationError({"due_date": "The deadline changed concurrently. Reload the loan before editing it."})
            starting = (update_fields is None or "status" in update_fields) and self.status in {
                self.LoanStatus.APPROVED, self.LoanStatus.BORROWED,
            } and (previous is None or previous.status in {self.LoanStatus.REQUESTED, self.LoanStatus.RESERVED})
            changed_fields = set()
            if starting:
                self.approved_at = timezone.now()
                changed_fields.add("approved_at")
                snapshot = self.first_confirmation_policy(self.approved_at, lock=True)
                for field, value in zip(self.POLICY_FIELDS, snapshot):
                    setattr(self, field, value)
                changed_fields.update(self.POLICY_FIELDS)
                if self.status == self.LoanStatus.BORROWED:
                    self.borrowed_at = self.approved_at
                    changed_fields.add("borrowed_at")
            borrowing_after_approval = (
                not starting and previous and previous.status == self.LoanStatus.APPROVED
                and self.status == self.LoanStatus.BORROWED
                and (update_fields is None or "status" in update_fields)
            )
            if borrowing_after_approval and self.borrowed_at is None and previous.approved_at is not None:
                # Record checkout without inventing/replacing the original confirmation.
                self.borrowed_at = timezone.now()
                changed_fields.add("borrowed_at")
            delivery_changed = (
                previous is not None and previous.delivery_days != self.delivery_days
                and (update_fields is None or "delivery_days" in update_fields)
            )
            changing_saved_due = (
                previous is not None and self.due_date != previous.due_date
                and (update_fields is None or "due_date" in update_fields)
            )
            protected_due = self.historical_deadline(previous) if previous and (delivery_changed or changing_saved_due) else None
            if protected_due is not None and changing_saved_due:
                raise ValidationError({"due_date": "This historical return date is fixed by the user-local cutover and cannot be changed."})
            needs_deadline = starting or delivery_changed or (borrowing_after_approval and self.due_date is None)
            if needs_deadline:
                confirmed_at = self.approved_at or self.borrowed_at
                # A newly recorded checkout is not evidence of a missing legacy confirmation.
                if previous and not starting:
                    confirmed_at = previous.approved_at or previous.borrowed_at
                if starting or confirmed_at or self.status not in {
                    self.LoanStatus.REQUESTED, self.LoanStatus.RESERVED, self.LoanStatus.NOTIFY,
                }:
                    self.due_date = protected_due if protected_due is not None else self.calculate_due_date(confirmed_at=confirmed_at)
                    changed_fields.add("due_date")
                    if (
                        protected_due is None and delivery_changed and previous.status == self.LoanStatus.OVERDUE
                        and self.status == self.LoanStatus.OVERDUE and self.due_date >= self.calendar_today()
                    ):
                        self.status = self.LoanStatus.BORROWED
                        changed_fields.add("status")
            self.full_clean()
            final_due = self.due_date
            if previous and update_fields is not None and "due_date" not in update_fields | changed_fields:
                final_due = previous.due_date
            self.email_deadline_revision = (previous.email_deadline_revision if previous else 0)
            if previous and final_due != previous.due_date:
                self.email_deadline_revision += 1
                changed_fields.add("email_deadline_revision")
            if update_fields is not None:
                kwargs["update_fields"] = update_fields | changed_fields
            super().save(*args, **kwargs)
            self.sync_book_copy_status(self.book_copy)
            from .email_events import record_loan_change
            record_loan_change(self, previous)

    def validate_confirmation_history(self, previous):
        for field in ("approved_at", "borrowed_at"):
            old = previous[field]
            if old is not None and getattr(self, field) != old:
                raise ValidationError({field: "The original confirmation/checkout timestamp cannot be changed."})
        if previous["status"] not in {self.LoanStatus.REQUESTED, self.LoanStatus.RESERVED, self.LoanStatus.NOTIFY}:
            if self.approved_at != previous["approved_at"]:
                raise ValidationError({"approved_at": "The original confirmation cannot be replaced."})
            if previous["approved_at"] is None and previous["borrowed_at"] is None and self.borrowed_at is not None:
                raise ValidationError({"borrowed_at": "A missing original confirmation cannot be replaced by an edit timestamp."})

    def historical_deadline(self, previous=None):
        """Keep pre-activation deadlines verbatim, including on delivery edits.

        Only an approved, fixed user-local boundary activates this protection.
        Retain it even if the new-confirmation flag is subsequently switched off.
        Unclassified old records stay unclassified; a missing anchor cannot be
        used to invent a new deadline or a Cairo/London policy.
        """
        boundary_value = getattr(settings, "LIBRARY_USER_LOCAL_CUTOVER_AT", "")
        if not boundary_value:
            return None
        if previous is None:
            if self._state.adding:
                return None
            previous = Loan.objects.filter(pk=self.pk).values(
                "status", "approved_at", "borrowed_at", "due_date",
            ).first()
        elif isinstance(previous, Loan):
            previous = {field: getattr(previous, field) for field in ("status", "approved_at", "borrowed_at", "due_date")}
        if not previous or previous["status"] in {
            self.LoanStatus.REQUESTED, self.LoanStatus.RESERVED, self.LoanStatus.NOTIFY,
        }:
            return None
        boundary = approved_utc_cutover(boundary_value, "LIBRARY_USER_LOCAL_CUTOVER_AT")
        if timezone.now() < boundary:
            return None  # A future approved boundary is not active yet.
        anchor = previous["approved_at"] or previous["borrowed_at"]
        if anchor is not None and require_aware(anchor) >= boundary:
            return None
        if previous["due_date"] is None:
            raise ValidationError({"due_date": "The historical return date is missing and cannot be reconstructed automatically."})
        return previous["due_date"]

    def calculate_due_date(self, *, confirmed_at=..., delivery_days=None):
        protected_due = self.historical_deadline()
        if protected_due is not None:
            return protected_due
        explicit = confirmed_at is not ...
        if confirmed_at is ...:
            confirmed_at = self.approved_at or self.borrowed_at
        days = self.delivery_days if delivery_days is None else delivery_days
        if self.calculation_policy and self.confirmation_local_date:
            return self.confirmation_local_date + timedelta(days=self.BORROWING_DAYS + days)
        if not confirmed_at or timezone.is_naive(confirmed_at):
            raise ValidationError({"delivery_days": "A reliable, timezone-aware confirmation is required. Existing dates have been preserved."})
        if explicit and self.status in {self.LoanStatus.REQUESTED, self.LoanStatus.RESERVED}:
            zone = confirmation_timezone(confirmed_at)
            return calculate_deadline(confirmed_at, zone.key, days, self.BORROWING_DAYS)
        raise ValidationError({"delivery_days": "The historical loan policy is unclassified. Verify its original timezone before recalculating; the saved deadline is preserved."})

    def first_confirmation_policy(self, confirmed_at, *, lock=False):
        # Student-local activation always needs its approved UTC boundary.
        # With no configured London transition, the legacy calendar is Cairo.
        # Existing snapshots and historical deadlines bypass this selection.
        confirmed_at = require_aware(confirmed_at)
        use_local = getattr(settings, "LIBRARY_USER_LOCAL_POLICY_ENABLED", False)
        if use_local:
            cutover = approved_utc_cutover(getattr(settings, "LIBRARY_USER_LOCAL_CUTOVER_AT", ""), "LIBRARY_USER_LOCAL_CUTOVER_AT")
            use_local = confirmed_at >= cutover
        if use_local:
            if not self.borrower_id:
                raise ValidationError({"delivery_days": "A linked student account with a saved timezone is required for the new policy."})
            profiles = UserProfile.objects.filter(user_id=self.borrower_id)
            profile = (profiles.select_for_update() if lock else profiles).first()
            try:
                zone = validated_timezone(profile.time_zone if profile else None)
            except ValidationError as exc:
                raise ValidationError({"delivery_days": "The student must save a valid timezone before this loan can be confirmed."}) from exc
            policy, operational = "user_local_v1", zone.key
        else:
            zone = confirmation_timezone(confirmed_at)
            policy = "cairo_v1" if zone.key == "Africa/Cairo" else "london_v1"
            operational = LONDON.key  # Preserve the previous local implementation.
        return policy, zone.key, operational, timezone.localdate(confirmed_at, timezone=zone)

    def validate_policy_history(self, previous):
        if any(getattr(self, field) != previous[field] for field in self.POLICY_FIELDS):
            if previous["calculation_policy"] is not None or previous["status"] not in {
                self.LoanStatus.REQUESTED, self.LoanStatus.RESERVED, self.LoanStatus.NOTIFY,
            }:
                raise ValidationError({"delivery_days": "The original loan timezone/policy snapshot is immutable; historical classification requires a separately approved operation."})

    def calendar_today(self, instant=None):
        zone = validated_timezone(self.operational_timezone) if self.operational_timezone else LONDON
        return timezone.localdate(instant or timezone.now(), timezone=zone)

    @property
    def return_days_late(self):
        if self.returned_at is None or self.due_date is None:
            return None
        # Preserve the existing operational policy; presentation is viewer-local.
        return max(0, (self.calendar_today(self.returned_at) - self.due_date).days)

    def preview_due_date(self, delivery_days):
        if self.status in {self.LoanStatus.REQUESTED, self.LoanStatus.RESERVED}:
            snapshot = self.first_confirmation_policy(timezone.now())
            return snapshot[3] + timedelta(days=self.BORROWING_DAYS + delivery_days)
        if delivery_days == self.delivery_days and self.due_date is not None:
            return self.due_date
        return self.calculate_due_date(delivery_days=delivery_days)

    @staticmethod
    def next_copy_status(book_copy: BookCopy) -> str:
        active_loans = Loan.objects.filter(book_copy=book_copy, status__in=Loan.active_statuses())
        if active_loans.filter(status__in=Loan.circulation_statuses()).exists():
            return BookCopy.CopyStatus.BORROWED
        if active_loans.filter(status__in=(Loan.LoanStatus.APPROVED, Loan.LoanStatus.RESERVED)).exists():
            return BookCopy.CopyStatus.RESERVED
        return BookCopy.CopyStatus.AVAILABLE

    @classmethod
    def sync_book_copy_status(cls, book_copy: BookCopy | None):
        if not book_copy:
            return
        next_status = cls.next_copy_status(book_copy)
        if book_copy.status != next_status:
            book_copy.status = next_status
            book_copy.save(update_fields=["status", "updated_at"])

    def delete(self, *args, **kwargs):
        book_copy = self.book_copy
        super().delete(*args, **kwargs)
        self.sync_book_copy_status(book_copy)


class NotificationLog(models.Model):
    class NotificationType(models.TextChoices):
        DUE_SOON = "due_soon", "Due Soon"
        OVERDUE = "overdue", "Overdue"

    loan = models.ForeignKey(Loan, on_delete=models.CASCADE, related_name="notification_logs")
    notification_type = models.CharField(max_length=30, choices=NotificationType.choices)
    recipient_email = models.EmailField(blank=True)
    sent_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "library_notification_log"
        ordering = ["-sent_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["loan", "notification_type"],
                name="library_notification_log_unique_loan_type",
            )
        ]

    def __str__(self) -> str:
        return f"{self.loan_id} - {self.notification_type}"


class BookFeedback(models.Model):
    class LearnedChoice(models.TextChoices):
        YES = "yes", "Yes"
        SOMEWHAT = "somewhat", "Somewhat"
        NO = "no", "No"

    class RecommendChoice(models.TextChoices):
        YES = "yes", "Yes"
        MAYBE = "maybe", "Maybe"
        NO = "no", "No"

    class QualityChoice(models.TextChoices):
        EXCELLENT = "excellent", "Excellent"
        GOOD = "good", "Good"
        FAIR = "fair", "Fair"
        POOR = "poor", "Poor"

    id = models.CharField(primary_key=True, max_length=50)
    loan = models.OneToOneField(Loan, on_delete=models.CASCADE, related_name="feedback")
    resource = models.ForeignKey(Resource, on_delete=models.CASCADE, related_name="feedback_entries")
    borrower = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="library_feedback_entries",
    )
    borrower_name = models.CharField(max_length=120, blank=True)
    borrower_email = models.EmailField(blank=True)
    learned_something = models.CharField(max_length=20, choices=LearnedChoice.choices)
    would_recommend = models.CharField(max_length=20, choices=RecommendChoice.choices)
    content_quality = models.CharField(max_length=20, choices=QualityChoice.choices)
    star_rating = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    comment = models.TextField(blank=True)
    submitted_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-submitted_at"]

    def __str__(self) -> str:
        return f"{self.resource.title} feedback ({self.star_rating}★)"


class BookRequest(models.Model):
    class RequestStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        ORDERED = "ordered", "Ordered"
        CANCELLED = "cancelled", "Cancelled"

    id = models.CharField(primary_key=True, max_length=50)
    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="book_requests",
    )
    resource = models.ForeignKey(Resource, on_delete=models.SET_NULL, blank=True, null=True, related_name="requests")
    student_name = models.CharField(max_length=120)
    student_email = models.EmailField()
    student_phone = models.CharField(max_length=30, blank=True)
    student_id_code = models.CharField(max_length=40, blank=True)
    book_title = models.CharField(max_length=255)
    reason = models.TextField(blank=True)
    category = models.CharField(max_length=100)
    needed_from = models.DateField(blank=True, null=True)
    needed_until = models.DateField(blank=True, null=True)
    submitted_at = models.DateTimeField(default=timezone.now)
    status = models.CharField(max_length=20, choices=RequestStatus.choices, default=RequestStatus.PENDING)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="reviewed_book_requests",
    )
    review_notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-submitted_at"]

    def __str__(self) -> str:
        return f"{self.book_title} - {self.student_name}"

    def save(self, *args, **kwargs):
        with transaction.atomic():
            is_new = self._state.adding and not type(self).objects.filter(pk=self.pk).exists()
            super().save(*args, **kwargs)
            if is_new:
                from .email_events import record_book_request
                record_book_request(self)


class SupportMessage(models.Model):
    class MessageStatus(models.TextChoices):
        NEW = "new", "New"
        IN_PROGRESS = "in_progress", "In Progress"
        RESOLVED = "resolved", "Resolved"

    id = models.CharField(primary_key=True, max_length=50)
    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="support_messages",
    )
    full_name = models.CharField(max_length=120)
    email = models.EmailField()
    course = models.CharField(max_length=160, blank=True)
    subject = models.CharField(max_length=120)
    message = models.TextField()
    status = models.CharField(max_length=20, choices=MessageStatus.choices, default=MessageStatus.NEW)
    submitted_at = models.DateTimeField(default=timezone.now)
    resolved_at = models.DateTimeField(blank=True, null=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="resolved_support_messages",
    )
    internal_notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-submitted_at"]

    def __str__(self) -> str:
        return f"{self.subject} - {self.full_name}"


def ensure_user_profile(user: User) -> UserProfile:
    profile, _ = UserProfile.objects.get_or_create(user=user)
    return profile


# Explicit imports register records without starting jobs or performing network I/O.
from .email_models import EmailAttempt, EmailOutbox  # noqa: E402,F401
