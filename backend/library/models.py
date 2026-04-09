from django.contrib.auth import get_user_model
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone


User = get_user_model()


class UserProfile(models.Model):
    class Role(models.TextChoices):
        STUDENT = "student", "Student"
        LIBRARIAN = "librarian", "Librarian"
        ADMIN = "admin", "Admin"

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="library_profile")
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.STUDENT)
    phone_number = models.CharField(max_length=30, blank=True)
    student_id_code = models.CharField(max_length=40, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["user__username"]

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
        return sum(1 for copy in self._copies_for_metrics() if copy.status == BookCopy.CopyStatus.AVAILABLE)

    @property
    def availability_status(self) -> str:
        statuses = [copy.status for copy in self._copies_for_metrics()]
        if not statuses:
            return BookCopy.CopyStatus.LOST
        if BookCopy.CopyStatus.AVAILABLE in statuses:
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
        labels = {
            BookCopy.CopyStatus.AVAILABLE: "Available now",
            BookCopy.CopyStatus.RESERVED: "Reserved",
            BookCopy.CopyStatus.BORROWED: "Borrowed",
            BookCopy.CopyStatus.LOST: "Unavailable",
            BookCopy.CopyStatus.MAINTENANCE: "Unavailable",
        }
        return labels.get(self.availability_status, "Unavailable")

    @property
    def can_borrow(self) -> bool:
        return self.availability_status == BookCopy.CopyStatus.AVAILABLE

    @property
    def can_reserve(self) -> bool:
        return self.availability_status == BookCopy.CopyStatus.BORROWED

    @property
    def expected_available_date(self):
        active_loans = self._active_circulation_loans()
        return active_loans[0].due_date if active_loans else None

    @property
    def availability_note(self) -> str:
        if self.availability_status == BookCopy.CopyStatus.BORROWED:
            if self.expected_available_date:
                return f"Expected back on {self.expected_available_date.isoformat()}"
            return "This book is currently borrowed. Return date is not available yet."
        if self.availability_status == BookCopy.CopyStatus.RESERVED:
            return "This book is reserved for the next student in line."
        if self.availability_status == BookCopy.CopyStatus.AVAILABLE:
            return "This book can be borrowed right now."
        return "Please contact the library team for availability updates."


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
            next_number = self.resource.copies.count() + 1
            self.accession_number = f"{self.resource_id}-{next_number:03d}"
        super().save(*args, **kwargs)


class Loan(models.Model):
    class LoanStatus(models.TextChoices):
        REQUESTED = "requested", "Requested"
        RESERVED = "reserved", "Reserved"
        APPROVED = "approved", "Approved"
        BORROWED = "borrowed", "Borrowed"
        RETURNED = "returned", "Returned"
        OVERDUE = "overdue", "Overdue"
        CANCELLED = "cancelled", "Cancelled"

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
    requested_at = models.DateTimeField(default=timezone.now)
    approved_at = models.DateTimeField(blank=True, null=True)
    borrowed_at = models.DateTimeField(blank=True, null=True)
    due_date = models.DateField(blank=True, null=True)
    returned_at = models.DateTimeField(blank=True, null=True)
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
            cls.LoanStatus.REQUESTED,
            cls.LoanStatus.APPROVED,
            cls.LoanStatus.BORROWED,
            cls.LoanStatus.OVERDUE,
        )

    @classmethod
    def terminal_statuses(cls) -> tuple[str, ...]:
        return (
            cls.LoanStatus.RETURNED,
            cls.LoanStatus.CANCELLED,
        )

    @classmethod
    def allowed_status_transitions(cls) -> dict[str, set[str]]:
        return {
            cls.LoanStatus.REQUESTED: {
                cls.LoanStatus.APPROVED,
                cls.LoanStatus.BORROWED,
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
            cls.LoanStatus.CANCELLED: set(),
        }

    def clean(self):
        super().clean()
        if not self.borrower_id and not (self.borrower_name and self.borrower_email):
            raise ValidationError("A loan must include either a linked borrower or a borrower name and email.")

        if self.pk:
            previous = Loan.objects.filter(pk=self.pk).values_list("status", flat=True).first()
            if previous and previous != self.status:
                allowed = self.allowed_status_transitions().get(previous, set())
                if self.status not in allowed:
                    raise ValidationError({"status": f"Cannot change loan status from {previous} to {self.status}."})

        if not self.book_copy_id or self.status not in self.active_statuses():
            return

        conflicting = Loan.objects.filter(
            book_copy__resource=self.book_copy.resource,
            status__in=self.active_statuses(),
        )
        if self.pk:
            conflicting = conflicting.exclude(pk=self.pk)

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

        if same_borrower_filter and conflicting.filter(same_borrower_filter).exists():
            raise ValidationError({"book_copy": "You already have an active borrow or reservation request for this book."})

        if self.status == self.LoanStatus.RESERVED:
            if conflicting.filter(status=self.LoanStatus.RESERVED).exists():
                raise ValidationError({"book_copy": "This copy already has an active reservation."})
        else:
            if conflicting.filter(status=self.LoanStatus.RESERVED).exists():
                raise ValidationError({"book_copy": "This copy is reserved for another student."})
            if conflicting.filter(status__in=self.circulation_statuses()).exists():
                raise ValidationError({"book_copy": "This copy already has an active borrowing flow."})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)
        self.sync_book_copy_status(self.book_copy)

    @staticmethod
    def next_copy_status(book_copy: BookCopy) -> str:
        active_loans = Loan.objects.filter(book_copy=book_copy, status__in=Loan.active_statuses())
        if active_loans.filter(status__in=Loan.circulation_statuses()).exists():
            return BookCopy.CopyStatus.BORROWED
        if active_loans.filter(status=Loan.LoanStatus.RESERVED).exists():
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


class BookRequest(models.Model):
    class RequestStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        ORDERED = "ordered", "Ordered"

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
