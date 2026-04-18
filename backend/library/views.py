import json
from datetime import datetime

from django.conf import settings
from django.core.cache import cache
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Count, Prefetch
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

from .models import BookCopy, BookRequest, Category, Loan, Resource, SupportMessage, ensure_user_profile
from .permissions import IsLibraryStaff
from .serializers import (
    AdminLoginSerializer,
    BookCopySerializer,
    BookRequestSerializer,
    CategorySerializer,
    LoanSerializer,
    LoanEmailSerializer,
    ResourceSerializer,
    SupportMessageSerializer,
    UserProfileSerializer,
)


CACHE_TTL = 120  # 2 minutes

CACHE_KEY_CATEGORIES = "api:categories:list"
CACHE_KEY_RESOURCES = "api:resources:list"


def bust_categories_cache():
    cache.delete(CACHE_KEY_CATEGORIES)


def bust_resources_cache():
    cache.delete(CACHE_KEY_RESOURCES)
    # Categories embed resourceCount so bust both when resources change.
    cache.delete(CACHE_KEY_CATEGORIES)


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
    queryset = Resource.objects.select_related("category").prefetch_related(
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

    def perform_create(self, serializer):
        resource = serializer.save()
        BookCopy.objects.get_or_create(
            resource=resource,
            accession_number=f"{resource.id}-001",
        )

    def create(self, request, *args, **kwargs):
        payload = request.data.copy()
        payload["id"] = payload.get("id") or f"r{int(datetime.now().timestamp() * 1000)}"
        payload["dateAdded"] = payload.get("dateAdded") or datetime.now().date().isoformat()
        serializer = self.get_serializer(data=payload)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        bust_resources_cache()
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def update(self, request, *args, **kwargs):
        response = super().update(request, *args, **kwargs)
        bust_resources_cache()
        return response

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

    def get_permissions(self):
        if self.action == "create":
            return [AllowAny()]
        return [IsLibraryStaff()]

    def create(self, request, *args, **kwargs):
        payload = request.data.copy()
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
            # Prefer attaching to an available copy. If none available and the
            # client is creating a generic request (`requested`) we still allow
            # creating a pending request attached to any usable copy so the
            # borrower can join the waiting list.
            target_copy = resource.copies.filter(status=BookCopy.CopyStatus.AVAILABLE).first()

            if not target_copy and requested_status == Loan.LoanStatus.REQUESTED:
                # pick any copy that isn't lost/maintenance to attach the request
                target_copy = resource.copies.exclude(status__in=[BookCopy.CopyStatus.LOST, BookCopy.CopyStatus.MAINTENANCE]).first()

            if requested_status == Loan.LoanStatus.RESERVED:
                target_copy = resource.copies.exclude(status__in=[BookCopy.CopyStatus.LOST, BookCopy.CopyStatus.MAINTENANCE]).first()
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
                    "loanId": updated_loan.id,
                    "copyNumber": updated_loan.book_copy.accession_number,
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

    @action(detail=True, methods=["post"], permission_classes=[IsLibraryStaff])
    def approve(self, request, pk=None):
        """
        Confirm one borrower from the pending request queue.

        Keeps the remaining pending requests in the queue, then
        transitions this loan directly to *borrowed* and fires the relevant webhook.

        We lock every active loan for this resource inside the transaction so that
        two librarians cannot simultaneously confirm two different requesters for
        the same book (the second save would raise a ValidationError via clean()).
        """
        loan = self.get_object()
        if loan.status != Loan.LoanStatus.REQUESTED:
            raise ValidationError({"status": "Only loans with status 'requested' can be approved through this action."})

        with transaction.atomic():
            # Lock ALL active loans for this resource so no concurrent approve
            # can slip through between our read and our write.
            locked = list(
                Loan.objects.select_for_update(nowait=False).filter(
                    book_copy__resource=loan.book_copy.resource,
                    status__in=Loan.active_statuses(),
                )
            )

            # After acquiring the lock, re-validate: nobody else may have
            # already confirmed a borrower while we were waiting.
            already_borrowed = any(
                l.status in (Loan.LoanStatus.BORROWED, Loan.LoanStatus.OVERDUE, Loan.LoanStatus.APPROVED)
                for l in locked
                if l.pk != loan.pk
            )
            if already_borrowed:
                raise ValidationError({"status": "This book is already borrowed by someone else."})

            # Re-read the target loan state from the locked queryset.
            fresh = next((l for l in locked if l.pk == loan.pk), None)
            if fresh is None or fresh.status != Loan.LoanStatus.REQUESTED:
                raise ValidationError({"status": "This request has already been processed."})

            now = timezone.now()
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


class BookRequestViewSet(viewsets.ModelViewSet):
    queryset = BookRequest.objects.select_related("requester", "reviewed_by", "resource")
    serializer_class = BookRequestSerializer

    def get_permissions(self):
        if self.action == "create":
            return [AllowAny()]
        return [IsLibraryStaff()]

    def create(self, request, *args, **kwargs):
        payload = request.data.copy()
        now = datetime.now().astimezone()
        payload["id"] = payload.get("id") or f"req{int(now.timestamp() * 1000)}"
        payload["submittedAt"] = payload.get("submittedAt") or now.isoformat()
        payload["status"] = payload.get("status") or BookRequest.RequestStatus.PENDING
        serializer = self.get_serializer(data=payload)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)


class SupportMessageViewSet(viewsets.ModelViewSet):
    queryset = SupportMessage.objects.select_related("requester", "resolved_by")
    serializer_class = SupportMessageSerializer

    def get_permissions(self):
        if self.action == "create":
            return [AllowAny()]
        return [IsLibraryStaff()]

    def create(self, request, *args, **kwargs):
        payload = request.data.copy()
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


class AuthMeView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile_data = UserProfileSerializer(ensure_user_profile(request.user)).data
        return Response({"user": profile_data}, status=status.HTTP_200_OK)


class AdminLogoutView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        Token.objects.filter(user=request.user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
