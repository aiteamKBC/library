import json
from datetime import datetime
from urllib.parse import quote

from django.conf import settings
from django.core.cache import cache
from django.core import signing
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Avg, Count, Prefetch, Q
from django.db.models.deletion import ProtectedError
from urllib.request import Request, urlopen
from django.utils.text import slugify
from rest_framework import status, viewsets
from rest_framework.authentication import TokenAuthentication
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.authtoken.models import Token
from django.utils import timezone

from .models import BookCopy, BookFeedback, BookRequest, Category, Loan, Resource, SupportMessage, UserProfile, ensure_user_profile
from .permissions import IsLibraryStaff, IsLibraryStaffOrApiKey
from .serializers import (
    AdminLoginSerializer,
    BookFeedbackSerializer,
    BookFeedbackSubmissionSerializer,
    BookCopySerializer,
    BookRequestSerializer,
    CategorySerializer,
    LoanSerializer,
    LoanEmailSerializer,
    ResourceSerializer,
    StudentDashboardSerializer,
    StudentEmailLoginSerializer,
    SupportMessageSerializer,
    UserProfileSerializer,
    UserProfileUpdateSerializer,
)
from .student_auth import (
    fetch_allowlisted_student,
    sync_student_account_from_allowlist,
)


CACHE_TTL = 120  # 2 minutes

CACHE_KEY_CATEGORIES = "api:categories:list"
CACHE_KEY_RESOURCES = "api:resources:list"
FEEDBACK_TOKEN_SALT = "library.book-feedback"
FEEDBACK_TOKEN_MAX_AGE_SECONDS = 60 * 60 * 24 * 180


def bust_categories_cache():
    cache.delete(CACHE_KEY_CATEGORIES)


def bust_resources_cache():
    cache.delete(CACHE_KEY_RESOURCES)
    # Categories embed resourceCount so bust both when resources change.
    cache.delete(CACHE_KEY_CATEGORIES)


def build_feedback_token(loan: Loan) -> str:
    return signing.dumps(
        {
            "loan_id": loan.id,
            "email": (loan.borrower_email or "").strip().lower(),
        },
        salt=FEEDBACK_TOKEN_SALT,
    )


def resolve_feedback_loan_from_token(token: str) -> Loan:
    try:
        payload = signing.loads(token, salt=FEEDBACK_TOKEN_SALT, max_age=FEEDBACK_TOKEN_MAX_AGE_SECONDS)
    except signing.BadSignature as exc:
        raise ValidationError({"token": "This feedback link is invalid or has expired."}) from exc

    loan_id = str(payload.get("loan_id") or "").strip()
    email = str(payload.get("email") or "").strip().lower()
    if not loan_id:
        raise ValidationError({"token": "This feedback link is invalid."})

    loan = Loan.objects.select_related("borrower", "book_copy", "book_copy__resource").filter(pk=loan_id).first()
    if loan is None:
        raise ValidationError({"token": "This feedback request could not be found."})

    if email and (loan.borrower_email or "").strip().lower() != email:
        raise ValidationError({"token": "This feedback link does not match the borrower record."})

    if loan.loan_type != Loan.LoanType.BORROW:
        raise ValidationError({"token": "Feedback is only available for completed borrowing records."})

    if loan.status != Loan.LoanStatus.RETURNED:
        raise ValidationError({"token": "Feedback becomes available after the book has been marked as returned."})

    return loan


def build_feedback_url(loan: Loan) -> str:
    base_url = getattr(settings, "FRONTEND_BASE_URL", "http://127.0.0.1:3000").strip().rstrip("/")
    token = build_feedback_token(loan)
    return f"{base_url}/feedback?token={quote(token, safe='')}"


def send_library_webhook(payload: dict[str, object]) -> bool:
    webhook_url = getattr(settings, "N8N_LIBRARY_WEBHOOK_URL", "").strip()
    if not webhook_url:
        return False

    request = Request(
        webhook_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=5) as response:
            return 200 <= getattr(response, "status", 200) < 300
    except Exception:
        # External webhook failures should not block the core library action.
        return False


def current_authenticated_user(request):
    user = getattr(request, "user", None)
    if user and user.is_authenticated:
        return user
    return None


def build_auth_session_payload(user):
    profile = ensure_user_profile(user)
    token, _ = Token.objects.get_or_create(user=user)
    return {
        "token": token.key,
        "user": UserProfileSerializer(profile).data,
    }


def populate_identity_from_account(
    request,
    payload,
    *,
    relation_key: str,
    name_key: str,
    email_key: str,
    phone_key: str | None = None,
    student_id_key: str | None = None,
):
    user = current_authenticated_user(request)
    if user is None:
        return

    profile = ensure_user_profile(user)
    payload[relation_key] = user.pk

    if not payload.get(name_key):
        payload[name_key] = user.get_full_name() or user.get_username()
    if not payload.get(email_key):
        payload[email_key] = user.email
    if phone_key and not payload.get(phone_key):
        payload[phone_key] = profile.phone_number
    if student_id_key and not payload.get(student_id_key):
        payload[student_id_key] = profile.student_id_code


def filter_for_current_account(queryset, *, user, relation_field: str, email_field: str):
    email = (user.email or "").strip()
    filters = Q(**{relation_field: user})
    if email:
        filters |= Q(**{f"{email_field}__iexact": email})
    return queryset.filter(filters).distinct()


def is_owned_by_current_account(*, user, related_user_id: int | None, email_value: str | None) -> bool:
    if related_user_id and related_user_id == getattr(user, "id", None):
        return True

    current_email = (getattr(user, "email", "") or "").strip().lower()
    target_email = (email_value or "").strip().lower()
    return bool(current_email and target_email and current_email == target_email)


class CategoryViewSet(viewsets.ModelViewSet):
    queryset = Category.objects.annotate(resourceCount=Count("resources"))
    serializer_class = CategorySerializer

    def get_permissions(self):
        if self.action in {"list", "retrieve"}:
            return [AllowAny()]
        return [IsLibraryStaff()]

    def list(self, request, *args, **kwargs):
        cached = cache.get(CACHE_KEY_CATEGORIES)
        if cached is not None:
            return Response(cached)
        response = super().list(request, *args, **kwargs)
        cache.set(CACHE_KEY_CATEGORIES, response.data, CACHE_TTL)
        return response

    def create(self, request, *args, **kwargs):
        payload = request.data.copy()
        if payload.get("name") and not payload.get("slug"):
            payload["slug"] = slugify(str(payload["name"]))
        serializer = self.get_serializer(data=payload)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        bust_categories_cache()
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        payload = request.data.copy()
        if payload.get("name") and "slug" not in payload:
            payload["slug"] = slugify(str(payload["name"]))
        serializer = self.get_serializer(instance, data=payload, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        bust_categories_cache()
        return Response(serializer.data)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        try:
            self.perform_destroy(instance)
        except ProtectedError as exc:
            raise ValidationError(
                {
                    "category": f'This category cannot be deleted because {instance.resources.count()} book(s) are still assigned to it.'
                }
            ) from exc
        bust_categories_cache()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ResourceViewSet(viewsets.ModelViewSet):
    queryset = Resource.objects.select_related("category").annotate(
        pending_borrow_request_total=Count(
            "copies__loans",
            filter=Q(
                copies__loans__status=Loan.LoanStatus.REQUESTED,
                copies__loans__loan_type=Loan.LoanType.BORROW,
            ),
            distinct=True,
        ),
        feedback_total=Count("feedback_entries", distinct=True),
        feedback_average_rating_value=Avg("feedback_entries__star_rating", distinct=True),
        feedback_recommend_total=Count(
            "feedback_entries",
            filter=Q(feedback_entries__would_recommend=BookFeedback.RecommendChoice.YES),
            distinct=True,
        ),
        feedback_learned_total=Count(
            "feedback_entries",
            filter=Q(
                feedback_entries__learned_something__in=(
                    BookFeedback.LearnedChoice.YES,
                    BookFeedback.LearnedChoice.SOMEWHAT,
                )
            ),
            distinct=True,
        ),
    ).prefetch_related(
        Prefetch(
            "copies",
            queryset=BookCopy.objects.prefetch_related(
                Prefetch(
                    "loans",
                    queryset=Loan.objects.filter(status__in=Loan.circulation_statuses()).order_by("due_date"),
                )
            ),
        )
    )
    serializer_class = ResourceSerializer

    def get_permissions(self):
        if self.action in {"list", "retrieve"}:
            return [AllowAny()]
        return [IsLibraryStaff()]

    def list(self, request, *args, **kwargs):
        cached = cache.get(CACHE_KEY_RESOURCES)
        if cached is not None:
            return Response(cached)
        response = super().list(request, *args, **kwargs)
        cache.set(CACHE_KEY_RESOURCES, response.data, CACHE_TTL)
        return response

    def create(self, request, *args, **kwargs):
        payload = request.data.copy()
        payload["id"] = payload.get("id") or f"r{int(datetime.now().timestamp() * 1000)}"
        payload["dateAdded"] = payload.get("dateAdded") or datetime.now().date().isoformat()
        serializer = self.get_serializer(data=payload)
        serializer.is_valid(raise_exception=True)
        inventory_count = serializer.validated_data.get("inventoryCount")

        try:
            with transaction.atomic():
                resource = serializer.save()
                resource.sync_copy_inventory(inventory_count)
        except DjangoValidationError as exc:
            raise ValidationError({"inventoryCount": exc.messages}) from exc

        bust_resources_cache()
        headers = self.get_success_headers(serializer.data)
        response_serializer = self.get_serializer(resource)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        inventory_count = serializer.validated_data.get("inventoryCount")

        try:
            with transaction.atomic():
                resource = serializer.save()
                if inventory_count is not None:
                    resource.sync_copy_inventory(inventory_count)
        except DjangoValidationError as exc:
            raise ValidationError({"inventoryCount": exc.messages}) from exc

        bust_resources_cache()
        response_serializer = self.get_serializer(resource)
        return Response(response_serializer.data)

    def destroy(self, request, *args, **kwargs):
        response = super().destroy(request, *args, **kwargs)
        bust_resources_cache()
        return response


class BookCopyViewSet(viewsets.ModelViewSet):
    queryset = BookCopy.objects.select_related("resource", "resource__category")
    serializer_class = BookCopySerializer
    permission_classes = [IsLibraryStaff]


class LoanViewSet(viewsets.ModelViewSet):
    queryset = Loan.objects.select_related("borrower", "approved_by", "book_copy", "book_copy__resource")
    serializer_class = LoanSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        status_param = self.request.query_params.get("status")
        if status_param:
            qs = qs.filter(status=status_param)
        due_before = self.request.query_params.get("due_before")
        if due_before:
            qs = qs.filter(due_date__lte=due_before)
        return qs

    def get_permissions(self):
        if self.action == "create":
            return [IsAuthenticated()]
        if self.action == "student_cancel":
            return [IsAuthenticated()]
        if self.action in {"list", "process_overdue"}:
            return [IsLibraryStaffOrApiKey()]
        return [IsLibraryStaff()]

    def create(self, request, *args, **kwargs):
        payload = request.data.copy()
        populate_identity_from_account(
            request,
            payload,
            relation_key="borrowerId",
            name_key="borrowerName",
            email_key="borrowerEmail",
            phone_key="borrowerPhone",
            student_id_key="borrowerStudentId",
        )
        now = timezone.now()
        payload["id"] = payload.get("id") or f"loan{int(now.timestamp() * 1000)}"
        payload["requestedAt"] = payload.get("requestedAt") or now.isoformat()
        if payload.get("status") != Loan.LoanStatus.RESERVED:
            payload["status"] = Loan.LoanStatus.REQUESTED
        resource_id = payload.get("resourceId")
        if resource_id and not payload.get("bookCopyId"):
            resource = Resource.objects.prefetch_related("copies").filter(pk=resource_id).first()
            if not resource:
                raise ValidationError({"resourceId": "Resource not found."})

            requested_status = payload.get("status") or Loan.LoanStatus.REQUESTED
            requested_loan_type = payload.get("loanType") or payload.get("loan_type") or Loan.LoanType.BORROW
            if requested_status == Loan.LoanStatus.REQUESTED and requested_loan_type == Loan.LoanType.BORROW and not resource.can_borrow:
                if resource.queue_full:
                    raise ValidationError({
                        "resourceId": "All currently available copies are already covered by pending requests. Please register for notify instead."
                    })
                raise ValidationError({
                    "resourceId": "No copies are currently open to borrow. Please register for notify instead."
                })
            # Prefer attaching to an available copy. If none available and the
            # client is creating a generic request (`requested`) we still allow
            # creating a pending request attached to any usable copy so the
            # borrower can join the waiting list.
            target_copy = resource.first_available_copy()

            if not target_copy and requested_status == Loan.LoanStatus.REQUESTED:
                # pick any copy that isn't lost/maintenance to attach the request
                target_copy = resource.first_usable_copy()

            if requested_status == Loan.LoanStatus.RESERVED:
                target_copy = resource.first_usable_copy()
                if not target_copy or resource.availability_status != BookCopy.CopyStatus.BORROWED:
                    raise ValidationError({"resourceId": "Only borrowed books can be reserved."})
                requested_from = payload.get("requestedFrom")
                expected_available_date = resource.expected_available_date
                if requested_from and expected_available_date and str(requested_from) < expected_available_date.isoformat():
                    raise ValidationError({
                        "requestedFrom": f"Reservation start date cannot start before {expected_available_date.isoformat()}."
                    })

            if not target_copy:
                raise ValidationError({"resourceId": "This book is not currently available to borrow."})

            payload["bookCopyId"] = target_copy.id

        if payload.get("status") == Loan.LoanStatus.REQUESTED:
            payload["borrowedAt"] = None
        if payload.get("status") == Loan.LoanStatus.BORROWED:
            payload["borrowedAt"] = payload.get("borrowedAt") or now.isoformat()

        serializer = self.get_serializer(data=payload)
        serializer.is_valid(raise_exception=True)
        loan = serializer.save()
        send_library_webhook(
            {
                "event": "loan_submitted",
                "mode": Loan.LoanStatus.REQUESTED,
                "name": loan.borrower_name,
                "email": loan.borrower_email,
                "phoneNumber": loan.borrower_phone,
                "bookTitle": loan.book_copy.resource.title,
                "neededFrom": loan.requested_from.isoformat() if loan.requested_from else (payload.get("borrowedAt")),
                "neededUntil": payload.get("dueDate"),
                "loanId": loan.id,
                "copyNumber": loan.book_copy.accession_number,
            }
        )
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        previous_status = instance.status
        payload = request.data.copy()
        next_status = payload.get("status")
        now = timezone.now()
        reapply_requests: list[Loan] = []

        if next_status == Loan.LoanStatus.RETURNED and not payload.get("returnedAt"):
            payload["returnedAt"] = now.isoformat()
        if next_status == Loan.LoanStatus.BORROWED and not payload.get("borrowedAt"):
            payload["borrowedAt"] = now.isoformat()

        serializer = self.get_serializer(instance, data=payload, partial=partial)
        serializer.is_valid(raise_exception=True)

        # Wrap the save and any cascading queue operations in one transaction so
        # a crash between the two cannot leave the queue in a half-updated state.
        with transaction.atomic():
            self.perform_update(serializer)
            updated_loan = serializer.instance

        # Any change that affects derived resource fields (expectedAvailableDate,
        # availabilityStatus) must bust the resource cache.
        if (
            (next_status and next_status != previous_status)
            or "dueDate" in payload
            or "due_date" in payload
        ):
            bust_resources_cache()

        notify_registrations: list[Loan] = []
        with transaction.atomic():
            if previous_status in {Loan.LoanStatus.BORROWED, Loan.LoanStatus.OVERDUE} and updated_loan.status == Loan.LoanStatus.RETURNED:
                # Keep all pending borrow requests in the queue and notify them.
                reapply_requests = list(
                    Loan.objects.select_for_update().filter(
                        book_copy__resource=updated_loan.book_copy.resource,
                        status=Loan.LoanStatus.REQUESTED,
                        loan_type=Loan.LoanType.BORROW,
                    ).order_by("requested_at")
                )
                # Collect notify registrations — send them a "book is back" email.
                notify_registrations = list(
                    Loan.objects.select_for_update().filter(
                        book_copy__resource=updated_loan.book_copy.resource,
                        status=Loan.LoanStatus.REQUESTED,
                        loan_type=Loan.LoanType.NOTIFY,
                    ).order_by("requested_at")
                )

        if previous_status in {Loan.LoanStatus.BORROWED, Loan.LoanStatus.OVERDUE} and updated_loan.status == Loan.LoanStatus.RETURNED:
            send_library_webhook(
                {
                    "event": "loan_returned",
                    "name": updated_loan.borrower_name,
                    "email": updated_loan.borrower_email,
                    "phoneNumber": updated_loan.borrower_phone,
                    "bookTitle": updated_loan.book_copy.resource.title,
                    "returnedAt": updated_loan.returned_at.isoformat() if updated_loan.returned_at else now.isoformat(),
                    "returnCondition": updated_loan.return_condition,
                    "returnConditionNotes": updated_loan.return_condition_notes,
                    "loanId": updated_loan.id,
                    "copyNumber": updated_loan.book_copy.accession_number,
                    "feedbackToken": build_feedback_token(updated_loan),
                    "feedbackUrl": build_feedback_url(updated_loan),
                }
            )

        if previous_status == Loan.LoanStatus.RESERVED and updated_loan.status == Loan.LoanStatus.BORROWED:
            send_library_webhook(
                {
                    "event": "reservation_confirmed",
                    "mode": Loan.LoanStatus.RESERVED,
                    "name": updated_loan.borrower_name,
                    "email": updated_loan.borrower_email,
                    "phoneNumber": updated_loan.borrower_phone,
                    "bookTitle": updated_loan.book_copy.resource.title,
                    "availableFrom": now.date().isoformat(),
                    "dueDate": updated_loan.due_date.isoformat() if updated_loan.due_date else None,
                    "loanId": updated_loan.id,
                    "copyNumber": updated_loan.book_copy.accession_number,
                }
            )
        elif previous_status in {Loan.LoanStatus.REQUESTED, Loan.LoanStatus.APPROVED} and updated_loan.status == Loan.LoanStatus.BORROWED:
            send_library_webhook(
                {
                    "event": "borrow_confirmed",
                    "mode": Loan.LoanStatus.BORROWED,
                    "name": updated_loan.borrower_name,
                    "email": updated_loan.borrower_email,
                    "phoneNumber": updated_loan.borrower_phone,
                    "bookTitle": updated_loan.book_copy.resource.title,
                    "borrowedAt": updated_loan.borrowed_at.isoformat() if updated_loan.borrowed_at else now.isoformat(),
                    "dueDate": updated_loan.due_date.isoformat() if updated_loan.due_date else None,
                    "loanId": updated_loan.id,
                    "copyNumber": updated_loan.book_copy.accession_number,
                }
            )
        elif previous_status in {Loan.LoanStatus.BORROWED, Loan.LoanStatus.REQUESTED, Loan.LoanStatus.APPROVED} and updated_loan.status == Loan.LoanStatus.OVERDUE:
            send_library_webhook(
                {
                    "event": "loan_overdue",
                    "mode": Loan.LoanStatus.OVERDUE,
                    "name": updated_loan.borrower_name,
                    "email": updated_loan.borrower_email,
                    "phoneNumber": updated_loan.borrower_phone,
                    "bookTitle": updated_loan.book_copy.resource.title,
                    "dueDate": updated_loan.due_date.isoformat() if updated_loan.due_date else None,
                    "markedOverdueAt": now.isoformat(),
                    "loanId": updated_loan.id,
                    "copyNumber": updated_loan.book_copy.accession_number,
                }
            )

        for pending_request in reapply_requests:
            send_library_webhook(
                {
                    "event": "book_now_available",
                    "mode": Loan.LoanStatus.REQUESTED,
                    "name": pending_request.borrower_name,
                    "email": pending_request.borrower_email,
                    "phoneNumber": pending_request.borrower_phone,
                    "bookTitle": pending_request.book_copy.resource.title,
                    "returnedAt": updated_loan.returned_at.isoformat() if updated_loan.returned_at else now.isoformat(),
                    "loanId": pending_request.id,
                    "copyNumber": pending_request.book_copy.accession_number,
                }
            )

        delivered_notify_registrations: list[Loan] = []
        for notify_reg in notify_registrations:
            delivered = send_library_webhook(
                {
                    "event": "notify_available",
                    "name": notify_reg.borrower_name,
                    "email": notify_reg.borrower_email,
                    "phoneNumber": notify_reg.borrower_phone,
                    "bookTitle": notify_reg.book_copy.resource.title,
                    "returnedAt": updated_loan.returned_at.isoformat() if updated_loan.returned_at else now.isoformat(),
                    "loanId": notify_reg.id,
                }
            )
            if delivered:
                delivered_notify_registrations.append(notify_reg)

        # Move successfully notified entries out of the active notify queue while
        # keeping them in circulation history for audit/reporting.
        for notify_reg in delivered_notify_registrations:
            notify_reg.status = Loan.LoanStatus.NOTIFY
            notify_reg.save(update_fields=["status"])

        return Response(serializer.data)

    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated], url_path="student-cancel")
    def student_cancel(self, request, pk=None):
        loan = self.get_queryset().filter(pk=pk).first()

        if loan is None:
            raise ValidationError({"detail": "This request could not be found."})

        if not is_owned_by_current_account(
            user=request.user,
            related_user_id=loan.borrower_id,
            email_value=loan.borrower_email,
        ):
            raise ValidationError({"detail": "You can only manage requests linked to your own account."})

        if loan.status != Loan.LoanStatus.REQUESTED:
            raise ValidationError({"status": "Only pending requests or alerts can be cancelled from your account."})

        loan.status = Loan.LoanStatus.CANCELLED
        loan.save(update_fields=["status"])
        bust_resources_cache()

        serializer = self.get_serializer(loan)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["post"], permission_classes=[IsLibraryStaffOrApiKey])
    def process_overdue(self, request):
        today = timezone.now().date()
        overdue_loans = Loan.objects.filter(
            status=Loan.LoanStatus.BORROWED,
            due_date__lte=today,
        ).select_related("book_copy", "book_copy__resource")

        results = []
        now = timezone.now()
        for loan in overdue_loans:
            loan.status = Loan.LoanStatus.OVERDUE
            loan.save(update_fields=["status"])
            send_library_webhook(
                {
                    "event": "loan_overdue",
                    "mode": Loan.LoanStatus.OVERDUE,
                    "name": loan.borrower_name,
                    "email": loan.borrower_email,
                    "phoneNumber": loan.borrower_phone,
                    "bookTitle": loan.book_copy.resource.title,
                    "dueDate": loan.due_date.isoformat() if loan.due_date else None,
                    "markedOverdueAt": now.isoformat(),
                    "loanId": loan.id,
                    "copyNumber": loan.book_copy.accession_number,
                }
            )
            results.append(
                {
                    "loanId": loan.id,
                    "borrowerName": loan.borrower_name,
                    "borrowerPhone": loan.borrower_phone,
                    "bookTitle": loan.book_copy.resource.title,
                    "dueDate": loan.due_date.isoformat() if loan.due_date else None,
                }
            )

        if results:
            bust_resources_cache()
        return Response({"count": len(results), "marked": results})

    @action(detail=True, methods=["post"], permission_classes=[IsLibraryStaff])
    def approve(self, request, pk=None):
        """
        Confirm one borrower from the pending request queue.

        Keeps the remaining pending requests in the queue, then
        transitions this loan directly to *borrowed* and assigns one currently
        available copy for the title.

        We lock the resource copies and active loans inside the transaction so
        concurrent approvals can safely consume different copies without
        double-assigning the same accession number.
        """
        loan = self.get_object()
        if loan.status != Loan.LoanStatus.REQUESTED:
            raise ValidationError({"status": "Only loans with status 'requested' can be approved through this action."})

        with transaction.atomic():
            locked_copies = list(
                BookCopy.objects.select_for_update(nowait=False)
                .filter(resource=loan.book_copy.resource)
                .order_by("accession_number")
            )
            locked = list(
                Loan.objects.select_for_update(nowait=False).filter(
                    book_copy__resource=loan.book_copy.resource,
                    status__in=Loan.active_statuses(),
                )
            )

            # Re-read the target loan state from the locked queryset.
            fresh = next((l for l in locked if l.pk == loan.pk), None)
            if fresh is None or fresh.status != Loan.LoanStatus.REQUESTED:
                raise ValidationError({"status": "This request has already been processed."})

            available_copy = next(
                (copy for copy in locked_copies if copy.status == BookCopy.CopyStatus.AVAILABLE),
                None,
            )
            if available_copy is None:
                raise ValidationError({"status": "No copies are currently available to approve for this title."})

            now = timezone.now()
            loan = fresh
            loan.book_copy = available_copy
            loan.status = Loan.LoanStatus.BORROWED
            loan.approved_at = now
            loan.borrowed_at = loan.borrowed_at or now
            loan.approved_by = request.user
            loan.save()

        send_library_webhook(
            {
                "event": "borrow_confirmed",
                "mode": Loan.LoanStatus.BORROWED,
                "name": loan.borrower_name,
                "email": loan.borrower_email,
                "phoneNumber": loan.borrower_phone,
                "bookTitle": loan.book_copy.resource.title,
                "borrowedAt": loan.borrowed_at.isoformat() if loan.borrowed_at else timezone.now().isoformat(),
                "dueDate": loan.due_date.isoformat() if loan.due_date else None,
                "loanId": loan.id,
                "copyNumber": loan.book_copy.accession_number,
            }
        )

        serializer = self.get_serializer(loan)
        return Response(serializer.data)

    @action(detail=True, methods=["post"], permission_classes=[IsLibraryStaff])
    def send_email(self, request, pk=None):
        loan = self.get_object()
        if not loan.borrower_email:
            raise ValidationError({"borrowerEmail": "This loan does not have a borrower email address."})

        serializer = LoanEmailSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        send_mail(
            subject=serializer.validated_data["subject"],
            message=serializer.validated_data["message"],
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[loan.borrower_email],
            fail_silently=False,
        )

        return Response({"detail": f"Email sent to {loan.borrower_email}."}, status=status.HTTP_200_OK)


class BookFeedbackViewSet(viewsets.ModelViewSet):
    queryset = BookFeedback.objects.select_related("loan", "resource", "borrower")
    serializer_class = BookFeedbackSerializer

    def get_permissions(self):
        if self.action in {"create", "context"}:
            return [AllowAny()]
        return [IsLibraryStaff()]

    def get_queryset(self):
        queryset = super().get_queryset()
        resource_id = self.request.query_params.get("resourceId")
        if resource_id:
            queryset = queryset.filter(resource_id=resource_id)
        return queryset

    @action(detail=False, methods=["get"], permission_classes=[AllowAny], url_path="context")
    def context(self, request):
        token = str(request.query_params.get("token") or "").strip()
        if not token:
            raise ValidationError({"token": "Missing feedback token."})

        loan = resolve_feedback_loan_from_token(token)
        existing_feedback = BookFeedback.objects.select_related("loan", "resource", "borrower").filter(loan=loan).first()

        borrower_name = loan.borrower_name
        if not borrower_name and loan.borrower:
            borrower_name = loan.borrower.get_full_name() or loan.borrower.get_username()

        payload = {
            "loanId": loan.id,
            "resourceId": loan.book_copy.resource_id,
            "bookTitle": loan.book_copy.resource.title,
            "borrowerName": borrower_name,
            "returnedAt": loan.returned_at.isoformat() if loan.returned_at else None,
            "alreadySubmitted": existing_feedback is not None,
            "feedback": BookFeedbackSerializer(existing_feedback).data if existing_feedback else None,
        }
        return Response(payload, status=status.HTTP_200_OK)

    def create(self, request, *args, **kwargs):
        serializer = BookFeedbackSubmissionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        loan = resolve_feedback_loan_from_token(serializer.validated_data["token"])
        if BookFeedback.objects.filter(loan=loan).exists():
            raise ValidationError({"detail": "Feedback has already been submitted for this returned book."})

        now = timezone.now()
        feedback = BookFeedback.objects.create(
            id=f"fdb{int(now.timestamp() * 1000)}",
            loan=loan,
            resource=loan.book_copy.resource,
            borrower=loan.borrower,
            borrower_name=loan.borrower_name,
            borrower_email=loan.borrower_email,
            learned_something=serializer.validated_data["learned_something"],
            would_recommend=serializer.validated_data["would_recommend"],
            content_quality=serializer.validated_data["content_quality"],
            star_rating=serializer.validated_data["star_rating"],
            comment=(serializer.validated_data.get("comment") or "").strip(),
            submitted_at=now,
        )
        bust_resources_cache()
        response_serializer = self.get_serializer(feedback)
        headers = self.get_success_headers(response_serializer.data)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED, headers=headers)


class BookRequestViewSet(viewsets.ModelViewSet):
    queryset = BookRequest.objects.select_related("requester", "reviewed_by", "resource")
    serializer_class = BookRequestSerializer

    def get_permissions(self):
        if self.action == "create":
            return [AllowAny()]
        if self.action == "student_cancel":
            return [IsAuthenticated()]
        return [IsLibraryStaff()]

    def create(self, request, *args, **kwargs):
        payload = request.data.copy()
        populate_identity_from_account(
            request,
            payload,
            relation_key="requesterId",
            name_key="studentName",
            email_key="studentEmail",
            phone_key="studentPhone",
            student_id_key="studentId",
        )
        now = datetime.now().astimezone()
        payload["id"] = payload.get("id") or f"req{int(now.timestamp() * 1000)}"
        payload["submittedAt"] = payload.get("submittedAt") or now.isoformat()
        payload["status"] = payload.get("status") or BookRequest.RequestStatus.PENDING
        serializer = self.get_serializer(data=payload)
        serializer.is_valid(raise_exception=True)
        book_request = serializer.save()
        send_library_webhook(
            {
                "event": "book_request_submitted",
                "requestId": book_request.id,
                "submittedAt": book_request.submitted_at.isoformat(),
                "bookTitle": book_request.book_title,
                "category": book_request.category,
                "reason": book_request.reason,
                "name": book_request.student_name,
                "email": book_request.student_email,
                "phoneNumber": book_request.student_phone,
                "studentId": book_request.student_id_code,
                "neededFrom": book_request.needed_from.isoformat() if book_request.needed_from else None,
                "neededUntil": book_request.needed_until.isoformat() if book_request.needed_until else None,
            }
        )
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated], url_path="student-cancel")
    def student_cancel(self, request, pk=None):
        book_request = self.get_queryset().filter(pk=pk).first()

        if book_request is None:
            raise ValidationError({"detail": "This request could not be found."})

        if not is_owned_by_current_account(
            user=request.user,
            related_user_id=book_request.requester_id,
            email_value=book_request.student_email,
        ):
            raise ValidationError({"detail": "You can only manage requests linked to your own account."})

        if book_request.status != BookRequest.RequestStatus.PENDING:
            raise ValidationError({"status": "Only pending book requests can be cancelled from your account."})

        book_request.status = BookRequest.RequestStatus.CANCELLED
        book_request.save(update_fields=["status"])

        serializer = self.get_serializer(book_request)
        return Response(serializer.data, status=status.HTTP_200_OK)


class SupportMessageViewSet(viewsets.ModelViewSet):
    queryset = SupportMessage.objects.select_related("requester", "resolved_by")
    serializer_class = SupportMessageSerializer

    def get_permissions(self):
        if self.action == "create":
            return [AllowAny()]
        return [IsLibraryStaff()]

    def create(self, request, *args, **kwargs):
        payload = request.data.copy()
        populate_identity_from_account(
            request,
            payload,
            relation_key="requesterId",
            name_key="fullName",
            email_key="email",
        )
        now = datetime.now().astimezone()
        payload["id"] = payload.get("id") or f"msg{int(now.timestamp() * 1000)}"
        payload["submittedAt"] = payload.get("submittedAt") or now.isoformat()
        payload["status"] = payload.get("status") or SupportMessage.MessageStatus.NEW
        serializer = self.get_serializer(data=payload)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        payload = request.data.copy()
        next_status = payload.get("status")
        if next_status == SupportMessage.MessageStatus.RESOLVED and not payload.get("resolvedAt"):
            payload["resolvedAt"] = timezone.now().isoformat()
        serializer = self.get_serializer(instance, data=payload, partial=partial)
        serializer.is_valid(raise_exception=True)
        serializer.save(resolved_by=request.user if next_status == SupportMessage.MessageStatus.RESOLVED else instance.resolved_by)
        return Response(serializer.data)


class AdminLoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = AdminLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        profile_data = UserProfileSerializer(serializer.validated_data["profile"]).data
        payload = {
            "token": serializer.validated_data["token"].key,
            "user": profile_data,
        }
        return Response(payload, status=status.HTTP_200_OK)


class StudentLoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = StudentEmailLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]

        try:
            allowlisted_student = fetch_allowlisted_student(email)
        except RuntimeError as exc:
            raise ValidationError({"detail": "Student sign-in is not configured yet. Please contact the library team."}) from exc

        if allowlisted_student is None:
            raise ValidationError({"email": "This email address is not approved for the KBC library system."})

        try:
            user = sync_student_account_from_allowlist(allowlisted_student)
        except ValueError as exc:
            raise ValidationError({"detail": str(exc)}) from exc

        payload = build_auth_session_payload(user)
        return Response(payload, status=status.HTTP_200_OK)


class AuthMeView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile_data = UserProfileSerializer(ensure_user_profile(request.user)).data
        return Response({"user": profile_data}, status=status.HTTP_200_OK)

    def patch(self, request):
        profile = ensure_user_profile(request.user)
        serializer = UserProfileUpdateSerializer(instance=profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        updated_profile = serializer.save()
        return Response({"user": UserProfileSerializer(updated_profile).data}, status=status.HTTP_200_OK)


class StudentDashboardView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        profile = ensure_user_profile(user)
        if profile.role != UserProfile.Role.STUDENT:
            return Response(
                {"detail": "This dashboard is available to student accounts only."},
                status=status.HTTP_403_FORBIDDEN,
            )

        loans = filter_for_current_account(
            Loan.objects.select_related("book_copy", "book_copy__resource"),
            user=user,
            relation_field="borrower",
            email_field="borrower_email",
        ).order_by("-requested_at")

        requests = filter_for_current_account(
            BookRequest.objects.select_related("resource", "requester", "reviewed_by"),
            user=user,
            relation_field="requester",
            email_field="student_email",
        ).order_by("-submitted_at")

        support_messages = filter_for_current_account(
            SupportMessage.objects.select_related("requester", "resolved_by"),
            user=user,
            relation_field="requester",
            email_field="email",
        ).order_by("-submitted_at")

        payload = {
            "user": profile,
            "loans": loans,
            "requests": requests,
            "supportMessages": support_messages,
        }
        serializer = StudentDashboardSerializer(payload)
        return Response(serializer.data, status=status.HTTP_200_OK)


class AdminLogoutView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        Token.objects.filter(user=request.user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
