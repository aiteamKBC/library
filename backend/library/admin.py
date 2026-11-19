from django.contrib import admin
from django.db.models import DateTimeField
from datetime import timezone as utc_timezone
from django.core.exceptions import ValidationError
from django.http import HttpResponseRedirect

from .models import BookCopy, BookFeedback, BookRequest, Category, Loan, NotificationLog, Resource, SupportMessage, UserProfile, EmailOutbox, EmailAttempt


class DeviceLocalModelAdmin(admin.ModelAdmin):
    change_form_template = "admin/library/device_change_form.html"
    change_list_template = "admin/library/device_change_list.html"

    class Media:
        js = ("library/device-time.js",)

    def timestamp_values(self, obj):
        if obj is None:
            return {}
        return {
            field.name: value.astimezone(utc_timezone.utc).isoformat()
            for field in obj._meta.fields if isinstance(field, DateTimeField)
            if (value := getattr(obj, field.name)) is not None
        }

    def render_change_form(self, request, context, *args, **kwargs):
        context["device_timestamp_fields"] = self.timestamp_values(context.get("original"))
        return super().render_change_form(request, context, *args, **kwargs)

    def changelist_view(self, request, extra_context=None):
        response = super().changelist_view(request, extra_context=extra_context)
        context = getattr(response, "context_data", None)
        if context and "cl" in context:
            context["device_timestamp_rows"] = [
                {"id": str(obj.pk), "fields": self.timestamp_values(obj)} for obj in context["cl"].result_list
            ]
        return response


@admin.register(UserProfile)
class UserProfileAdmin(DeviceLocalModelAdmin):
    list_display = ("user", "role", "phone_number", "student_id_code", "time_zone", "time_zone_source", "updated_at")
    readonly_fields = ("time_zone", "time_zone_source", "time_zone_updated_at")
    list_filter = ("role",)
    search_fields = ("user__username", "user__email", "user__first_name", "user__last_name", "phone_number", "student_id_code")


@admin.register(Category)
class CategoryAdmin(DeviceLocalModelAdmin):
    list_display = ("name", "slug")
    search_fields = ("name", "slug")


@admin.register(Resource)
class ResourceAdmin(DeviceLocalModelAdmin):
    list_display = ("id", "title", "author", "category", "type", "available_copy_count", "date_added")
    list_filter = ("category", "type", "featured", "popular")
    search_fields = ("id", "title", "author", "isbn13", "isbn10")

    @admin.display(description="Available copies")
    def available_copy_count(self, obj: Resource) -> int:
        return obj.available_copies


@admin.register(BookCopy)
class BookCopyAdmin(DeviceLocalModelAdmin):
    list_display = ("accession_number", "resource", "status", "shelf_location", "updated_at")
    list_filter = ("status", "resource__category")
    search_fields = ("accession_number", "resource__title", "resource__author")


@admin.register(Loan)
class LoanAdmin(DeviceLocalModelAdmin):
    list_display = ("id", "book_copy", "display_borrower", "borrower_phone", "borrower_student_id", "status", "return_condition", "requested_at", "due_date", "returned_at")
    list_filter = ("status", "return_condition")

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        try:
            return super().changeform_view(request, object_id, form_url, extra_context)
        except ValidationError as exc:
            # The parent admin transaction has rolled back before this handler.
            self.message_user(request, " ".join(exc.messages), level="ERROR")
            return HttpResponseRedirect(request.path)

    def get_readonly_fields(self, request, obj=None):
        fields = ("approved_at", "borrowed_at", *Loan.POLICY_FIELDS, "email_deadline_revision")
        if obj and (obj.approved_at or obj.borrowed_at or obj.status not in {
            Loan.LoanStatus.REQUESTED, Loan.LoanStatus.RESERVED, Loan.LoanStatus.NOTIFY,
        }):
            fields += ("due_date",)
        return fields

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
class BookRequestAdmin(DeviceLocalModelAdmin):
    list_display = ("id", "book_title", "student_name", "student_phone", "student_id_code", "category", "status", "submitted_at")
    list_filter = ("status", "category")
    search_fields = ("id", "book_title", "student_name", "student_email", "student_phone", "student_id_code")


@admin.register(NotificationLog)
class NotificationLogAdmin(DeviceLocalModelAdmin):
    list_display = ("loan", "notification_type", "recipient_email", "sent_at")
    list_filter = ("notification_type", "sent_at")
    search_fields = (
        "loan__id",
        "loan__borrower_name",
        "loan__borrower_email",
        "loan__book_copy__resource__title",
        "recipient_email",
    )


@admin.register(BookFeedback)
class BookFeedbackAdmin(DeviceLocalModelAdmin):
    list_display = ("resource", "borrower_name", "borrower_email", "star_rating", "would_recommend", "learned_something", "content_quality", "submitted_at")
    list_filter = ("would_recommend", "learned_something", "content_quality", "star_rating", "submitted_at")
    search_fields = ("resource__title", "borrower_name", "borrower_email", "comment", "loan__id")


@admin.register(SupportMessage)
class SupportMessageAdmin(DeviceLocalModelAdmin):
    list_display = ("id", "subject", "full_name", "email", "course", "status", "submitted_at", "resolved_at")
    list_filter = ("status", "subject")
    search_fields = ("id", "subject", "full_name", "email", "course", "message")


class ReadOnlyEmailAdmin(DeviceLocalModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(EmailOutbox)
class EmailOutboxAdmin(ReadOnlyEmailAdmin):
    list_display = ("id", "event_type", "recipient_role", "status", "available_at", "attempts_count")
    list_filter = ("status", "message_kind", "recipient_role")
    search_fields = ("idempotency_key", "event_type", "source_id", "error_code")
    actions = ("retry_safe_messages",)

    @admin.action(description="Retry selected definitively failed/blocked emails (never accepted/uncertain)", permissions=["view"])
    def retry_safe_messages(self, request, queryset):
        from .email_worker import retry_message
        count = rejected = 0
        for pk in queryset.values_list("pk", flat=True):
            try:
                row = retry_message(pk, actor=request.user)
                self.log_change(request, row, "Queued a safe email retry. No delivery performed by admin request.")
                count += 1
            except ValidationError:
                rejected += 1
        self.message_user(request, f"Queued: {count}. Rejected by safety checks: {rejected}. No email sent by this action.")


@admin.register(EmailAttempt)
class EmailAttemptAdmin(ReadOnlyEmailAdmin):
    list_display = ("message", "attempt_number", "result", "started_at", "finished_at", "http_status")
    list_filter = ("result",)
