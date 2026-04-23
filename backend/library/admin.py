from django.contrib import admin

from .models import BookCopy, BookRequest, Category, Loan, NotificationLog, Resource, SupportMessage


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug")
    search_fields = ("name", "slug")


@admin.register(Resource)
class ResourceAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "author", "category", "type", "available_copy_count", "date_added")
    list_filter = ("category", "type", "featured", "popular")
    search_fields = ("id", "title", "author", "isbn13", "isbn10")

    @admin.display(description="Available copies")
    def available_copy_count(self, obj: Resource) -> int:
        return obj.available_copies


@admin.register(BookCopy)
class BookCopyAdmin(admin.ModelAdmin):
    list_display = ("accession_number", "resource", "status", "shelf_location", "updated_at")
    list_filter = ("status", "resource__category")
    search_fields = ("accession_number", "resource__title", "resource__author")


@admin.register(Loan)
class LoanAdmin(admin.ModelAdmin):
    list_display = ("id", "book_copy", "display_borrower", "borrower_phone", "borrower_student_id", "status", "return_condition", "requested_at", "due_date", "returned_at")
    list_filter = ("status", "return_condition")
    search_fields = (
        "id",
        "book_copy__accession_number",
        "book_copy__resource__title",
        "borrower__username",
        "borrower__email",
        "borrower_name",
        "borrower_email",
        "borrower_phone",
        "borrower_student_id",
    )

    @admin.display(description="Borrower")
    def display_borrower(self, obj: Loan) -> str:
        if obj.borrower:
            return obj.borrower.get_username()
        return obj.borrower_name or "Unknown"


@admin.register(BookRequest)
class BookRequestAdmin(admin.ModelAdmin):
    list_display = ("id", "book_title", "student_name", "student_phone", "student_id_code", "category", "status", "submitted_at")
    list_filter = ("status", "category")
    search_fields = ("id", "book_title", "student_name", "student_email", "student_phone", "student_id_code")


@admin.register(NotificationLog)
class NotificationLogAdmin(admin.ModelAdmin):
    list_display = ("loan", "notification_type", "recipient_email", "sent_at")
    list_filter = ("notification_type", "sent_at")
    search_fields = (
        "loan__id",
        "loan__borrower_name",
        "loan__borrower_email",
        "loan__book_copy__resource__title",
        "recipient_email",
    )


@admin.register(SupportMessage)
class SupportMessageAdmin(admin.ModelAdmin):
    list_display = ("id", "subject", "full_name", "email", "course", "status", "submitted_at", "resolved_at")
    list_filter = ("status", "subject")
    search_fields = ("id", "subject", "full_name", "email", "course", "message")
