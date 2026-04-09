import json
from datetime import datetime

from django.conf import settings
from django.core.mail import send_mail
from django.db.models import Prefetch
from urllib.request import Request, urlopen
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


def send_library_webhook(payload: dict[str, object]) -> None:
    webhook_url = getattr(settings, "N8N_LIBRARY_WEBHOOK_URL", "").strip()
    if not webhook_url:
        return

    request = Request(
        webhook_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=5):
            pass
    except Exception:
        # External webhook failures should not block the core library action.
        return


class CategoryViewSet(viewsets.ModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer

    def get_permissions(self):
        if self.action in {"list", "retrieve"}:
            return [AllowAny()]
        return [IsLibraryStaff()]


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
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)


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
        resource_id = payload.get("resourceId")
        if resource_id and not payload.get("bookCopyId"):
            resource = Resource.objects.prefetch_related("copies").filter(pk=resource_id).first()
            if not resource:
                raise ValidationError({"resourceId": "Resource not found."})

            requested_status = payload.get("status") or Loan.LoanStatus.BORROWED
            target_copy = resource.copies.filter(status=BookCopy.CopyStatus.AVAILABLE).first()

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
            elif not target_copy:
                raise ValidationError({"resourceId": "This book is not currently available to borrow."})

            payload["bookCopyId"] = target_copy.id

        if payload.get("status") == Loan.LoanStatus.BORROWED:
            payload["borrowedAt"] = payload.get("borrowedAt") or now.isoformat()
        if payload.get("status") == Loan.LoanStatus.RESERVED:
            payload["borrowedAt"] = None

        serializer = self.get_serializer(data=payload)
        serializer.is_valid(raise_exception=True)
        loan = serializer.save()
        send_library_webhook(
            {
                "event": "loan_submitted",
                "mode": payload.get("status") or Loan.LoanStatus.BORROWED,
                "name": loan.borrower_name,
                "email": loan.borrower_email,
                "phoneNumber": loan.borrower_phone,
                "bookTitle": loan.book_copy.resource.title,
                "neededFrom": payload.get("requestedFrom") or payload.get("borrowedAt"),
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

        if next_status == Loan.LoanStatus.RETURNED and not payload.get("returnedAt"):
            payload["returnedAt"] = now.isoformat()
        if next_status == Loan.LoanStatus.BORROWED and not payload.get("borrowedAt"):
            payload["borrowedAt"] = now.isoformat()

        serializer = self.get_serializer(instance, data=payload, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        updated_loan = serializer.instance

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
