import os

from django.contrib.auth import authenticate, get_user_model
from rest_framework.authtoken.models import Token
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .models import BookCopy, BookRequest, Category, Loan, Resource, SupportMessage, UserProfile, ensure_user_profile

User = get_user_model()


def split_full_name(full_name: str) -> tuple[str, str]:
    normalized = " ".join(full_name.strip().split())
    if not normalized:
        return "", ""
    first_name, _, last_name = normalized.partition(" ")
    return first_name, last_name


def authenticate_by_identifier(identifier: str, password: str):
    user = authenticate(username=identifier, password=password)
    if user is None and "@" in identifier:
        matched_user = User.objects.filter(email__iexact=identifier).first()
        if matched_user:
            user = authenticate(username=matched_user.get_username(), password=password)
    return user


class CategorySerializer(serializers.ModelSerializer):
    resourceCount = serializers.IntegerField(read_only=True)

    class Meta:
        model = Category
        fields = ["id", "name", "slug", "description", "color", "icon", "resourceCount"]


class ResourceSerializer(serializers.ModelSerializer):
    category = serializers.CharField(source="category.name", read_only=True)
    categoryId = serializers.SlugRelatedField(source="category", slug_field="slug", queryset=Category.objects.all())
    dateAdded = serializers.DateField(source="date_added", required=False)
    coverColor = serializers.CharField(source="cover_color", required=False)
    publicationYear = serializers.CharField(source="publication_year", allow_blank=True, required=False)
    pageCount = serializers.IntegerField(source="page_count", allow_null=True, required=False)
    edition = serializers.CharField(allow_blank=True, required=False)
    coverImage = serializers.URLField(source="cover_image", allow_blank=True, required=False)
    infoLink = serializers.URLField(source="info_link", allow_blank=True, required=False)
    inventoryCount = serializers.IntegerField(write_only=True, required=False, min_value=1)
    totalCopies = serializers.ReadOnlyField(source="total_copies")
    availableCopies = serializers.ReadOnlyField(source="available_copies")
    borrowableCopies = serializers.ReadOnlyField(source="borrowable_copies")
    pendingBorrowRequests = serializers.ReadOnlyField(source="pending_borrow_request_count")
    queueFull = serializers.ReadOnlyField(source="queue_full")
    availabilityStatus = serializers.ReadOnlyField(source="availability_status")
    availabilityLabel = serializers.ReadOnlyField(source="availability_label")
    expectedAvailableDate = serializers.DateField(source="expected_available_date", read_only=True)
    availabilityNote = serializers.ReadOnlyField(source="availability_note")
    canBorrow = serializers.ReadOnlyField(source="can_borrow")
    canReserve = serializers.ReadOnlyField(source="can_reserve")

    class Meta:
        model = Resource
        fields = [
            "id",
            "title",
            "description",
            "category",
            "categoryId",
            "type",
            "level",
            "author",
            "publisher",
            "edition",
            "publicationYear",
            "pageCount",
            "isbn13",
            "isbn10",
            "coverImage",
            "infoLink",
            "dateAdded",
            "featured",
            "popular",
            "coverColor",
            "inventoryCount",
            "totalCopies",
            "availableCopies",
            "borrowableCopies",
            "pendingBorrowRequests",
            "queueFull",
            "availabilityStatus",
            "availabilityLabel",
            "expectedAvailableDate",
            "availabilityNote",
            "canBorrow",
            "canReserve",
        ]

    def create(self, validated_data):
        validated_data.pop("inventoryCount", None)
        return super().create(validated_data)

    def update(self, instance, validated_data):
        validated_data.pop("inventoryCount", None)
        return super().update(instance, validated_data)


class BookCopySerializer(serializers.ModelSerializer):
    resourceId = serializers.CharField(source="resource_id", read_only=True)
    resourceTitle = serializers.CharField(source="resource.title", read_only=True)

    class Meta:
        model = BookCopy
        fields = [
            "id",
            "accession_number",
            "resourceId",
            "resourceTitle",
            "status",
            "shelf_location",
            "notes",
            "added_at",
            "updated_at",
        ]
        read_only_fields = ["id", "added_at", "updated_at", "resourceId", "resourceTitle"]


class LoanSerializer(serializers.ModelSerializer):
    borrowerId = serializers.IntegerField(source="borrower_id", allow_null=True, required=False)
    borrowerName = serializers.CharField(source="borrower_name", allow_blank=True, required=False)
    borrowerEmail = serializers.EmailField(source="borrower_email", allow_blank=True, required=False)
    borrowerPhone = serializers.CharField(source="borrower_phone", allow_blank=True, required=False)
    borrowerStudentId = serializers.CharField(source="borrower_student_id", allow_blank=True, required=False)
    approvedById = serializers.IntegerField(source="approved_by_id", allow_null=True, required=False)
    bookCopyId = serializers.IntegerField(source="book_copy_id", required=False)
    resourceId = serializers.CharField(source="book_copy.resource_id", read_only=True)
    requestedFrom = serializers.DateField(source="requested_from", allow_null=True, required=False)
    loanType = serializers.CharField(source="loan_type", required=False)
    bookTitle = serializers.CharField(source="book_copy.resource.title", read_only=True)
    accessionNumber = serializers.CharField(source="book_copy.accession_number", read_only=True)
    availabilityStatus = serializers.CharField(source="book_copy.status", read_only=True)
    requestedAt = serializers.DateTimeField(source="requested_at", required=False)
    approvedAt = serializers.DateTimeField(source="approved_at", allow_null=True, required=False)
    borrowedAt = serializers.DateTimeField(source="borrowed_at", allow_null=True, required=False)
    dueDate = serializers.DateField(source="due_date", allow_null=True, required=False)
    returnedAt = serializers.DateTimeField(source="returned_at", allow_null=True, required=False)
    returnCondition = serializers.CharField(source="return_condition", allow_blank=True, required=False)
    returnConditionNotes = serializers.CharField(source="return_condition_notes", allow_blank=True, required=False)
    returnEvidence = serializers.FileField(source="return_evidence", allow_empty_file=False, allow_null=True, required=False)
    returnEvidenceName = serializers.SerializerMethodField()

    class Meta:
        model = Loan
        fields = [
            "id",
            "borrowerId",
            "borrowerName",
            "borrowerEmail",
            "borrowerPhone",
            "borrowerStudentId",
            "approvedById",
            "bookCopyId",
            "resourceId",
            "requestedFrom",
            "loanType",
            "bookTitle",
            "accessionNumber",
            "availabilityStatus",
            "status",
            "requestedAt",
            "approvedAt",
            "borrowedAt",
            "dueDate",
            "returnedAt",
            "returnCondition",
            "returnConditionNotes",
            "returnEvidence",
            "returnEvidenceName",
            "notes",
        ]
        read_only_fields = ["bookTitle", "accessionNumber", "availabilityStatus"]

    def get_returnEvidenceName(self, obj: Loan):
        if not obj.return_evidence:
            return None
        return os.path.basename(obj.return_evidence.name)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        borrower = attrs.get("borrower", getattr(self.instance, "borrower", None))
        borrower_name = attrs.get("borrower_name", getattr(self.instance, "borrower_name", ""))
        borrower_email = attrs.get("borrower_email", getattr(self.instance, "borrower_email", ""))
        if not borrower and not (borrower_name and borrower_email):
            raise serializers.ValidationError("Borrower details are required.")
        if not borrower and borrower_name and "@" in borrower_name:
            raise serializers.ValidationError({"borrowerName": "Please enter your full name in the name field."})
        borrower_phone = attrs.get("borrower_phone", getattr(self.instance, "borrower_phone", ""))
        if self.instance is None and not borrower and not borrower_phone:
            raise serializers.ValidationError("A phone number is required for borrowing and reservation requests.")

        next_status = attrs.get("status", getattr(self.instance, "status", Loan.LoanStatus.REQUESTED))
        return_evidence = attrs.get("return_evidence", getattr(self.instance, "return_evidence", None))
        requested_from = attrs.get("requested_from")
        book_copy = None

        if attrs.get("return_evidence") is not None:
            upload = attrs["return_evidence"]
            extension = os.path.splitext(upload.name or "")[1].lower()
            if extension not in {".jpg", ".jpeg", ".png", ".webp", ".pdf"}:
                raise serializers.ValidationError({
                    "returnEvidence": "Please upload JPG, PNG, WEBP, or PDF evidence.",
                })
            if upload.size > 10 * 1024 * 1024:
                raise serializers.ValidationError({
                    "returnEvidence": "Please upload a file smaller than 10 MB.",
                })

        book_copy_id = attrs.get("book_copy_id")
        if book_copy_id:
            book_copy = BookCopy.objects.select_related("resource").filter(pk=book_copy_id).first()
        elif self.instance is not None:
            book_copy = self.instance.book_copy

        if next_status == Loan.LoanStatus.RESERVED and requested_from and book_copy:
            expected_available_date = book_copy.resource.expected_available_date
            if expected_available_date and requested_from < expected_available_date:
                raise serializers.ValidationError({
                    "requestedFrom": f"Reservation start date cannot start before {expected_available_date.isoformat()}."
                })
        return_condition = attrs.get("return_condition", getattr(self.instance, "return_condition", ""))
        current_status = getattr(self.instance, "status", None)
        if next_status == Loan.LoanStatus.RETURNED and current_status != Loan.LoanStatus.RETURNED and not return_condition:
            raise serializers.ValidationError({
                "returnCondition": "Please select the condition of the returned book.",
            })
        if (
            next_status == Loan.LoanStatus.RETURNED
            and current_status != Loan.LoanStatus.RETURNED
            and return_condition in {Loan.ReturnCondition.DAMAGED, Loan.ReturnCondition.TORN}
            and not return_evidence
        ):
            raise serializers.ValidationError({
                "returnEvidence": "Please attach photo or PDF evidence for damaged or repair-needed returns.",
            })
        return attrs

    def create(self, validated_data):
        validated_data.pop("resourceId", None)
        try:
            return super().create(validated_data)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict if hasattr(exc, "message_dict") else exc.messages) from exc

    def update(self, instance, validated_data):
        validated_data.pop("resourceId", None)
        try:
            return super().update(instance, validated_data)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict if hasattr(exc, "message_dict") else exc.messages) from exc


class BookRequestSerializer(serializers.ModelSerializer):
    studentName = serializers.CharField(source="student_name")
    studentEmail = serializers.EmailField(source="student_email")
    studentPhone = serializers.CharField(source="student_phone", allow_blank=True, required=False)
    studentId = serializers.CharField(source="student_id_code", allow_blank=True, required=False)
    bookTitle = serializers.CharField(source="book_title")
    reason = serializers.CharField(allow_blank=True, required=False)
    neededFrom = serializers.DateField(source="needed_from", allow_null=True, required=False)
    neededUntil = serializers.DateField(source="needed_until", allow_null=True, required=False)
    submittedAt = serializers.DateTimeField(source="submitted_at", required=False)
    requesterId = serializers.IntegerField(source="requester_id", allow_null=True, required=False)
    resourceId = serializers.CharField(source="resource_id", allow_null=True, required=False)
    reviewedById = serializers.IntegerField(source="reviewed_by_id", allow_null=True, required=False)
    reviewNotes = serializers.CharField(source="review_notes", allow_blank=True, required=False)

    class Meta:
        model = BookRequest
        fields = [
            "id",
            "requesterId",
            "resourceId",
            "studentName",
            "studentEmail",
            "studentPhone",
            "studentId",
            "bookTitle",
            "reason",
            "category",
            "neededFrom",
            "neededUntil",
            "submittedAt",
            "status",
            "reviewedById",
            "reviewNotes",
        ]
        read_only_fields = ["submittedAt"]

    def validate(self, attrs):
        attrs = super().validate(attrs)
        student_phone = attrs.get("student_phone", getattr(self.instance, "student_phone", ""))
        if self.instance is None and not student_phone:
            raise serializers.ValidationError("A phone number is required for library requests.")
        student_name = attrs.get("student_name", getattr(self.instance, "student_name", ""))
        if student_name and "@" in student_name:
            raise serializers.ValidationError({"studentName": "Please enter your full name in the name field."})
        return attrs


class SupportMessageSerializer(serializers.ModelSerializer):
    fullName = serializers.CharField(source="full_name")
    submittedAt = serializers.DateTimeField(source="submitted_at", required=False)
    resolvedAt = serializers.DateTimeField(source="resolved_at", allow_null=True, required=False)
    internalNotes = serializers.CharField(source="internal_notes", allow_blank=True, required=False)
    requesterId = serializers.IntegerField(source="requester_id", allow_null=True, required=False)
    resolvedById = serializers.IntegerField(source="resolved_by_id", allow_null=True, required=False)

    class Meta:
        model = SupportMessage
        fields = [
            "id",
            "requesterId",
            "fullName",
            "email",
            "course",
            "subject",
            "message",
            "status",
            "submittedAt",
            "resolvedAt",
            "resolvedById",
            "internalNotes",
        ]
        read_only_fields = ["submittedAt", "resolvedAt", "requesterId", "resolvedById"]


class UserProfileSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="user.username", read_only=True)
    email = serializers.EmailField(source="user.email", read_only=True)
    fullName = serializers.SerializerMethodField()

    class Meta:
        model = UserProfile
        fields = ["username", "email", "fullName", "role", "phone_number", "student_id_code"]

    def get_fullName(self, obj: UserProfile) -> str:
        return obj.user.get_full_name() or obj.user.get_username()


class AuthSessionSerializer(serializers.Serializer):
    token = serializers.CharField()
    user = UserProfileSerializer()


class LibraryLoginSerializer(serializers.Serializer):
    identifier = serializers.CharField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        identifier = attrs["identifier"].strip()
        password = attrs["password"]
        user = authenticate_by_identifier(identifier, password)

        if user is None:
            raise serializers.ValidationError("Invalid credentials.")

        profile = ensure_user_profile(user)
        if user.is_superuser or user.is_staff or profile.role in {UserProfile.Role.ADMIN, UserProfile.Role.LIBRARIAN}:
            raise serializers.ValidationError("This account uses the library admin portal.")
        token, _ = Token.objects.get_or_create(user=user)
        attrs["user"] = user
        attrs["profile"] = profile
        attrs["token"] = token
        return attrs


class AdminLoginSerializer(serializers.Serializer):
    identifier = serializers.CharField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        identifier = attrs["identifier"].strip()
        password = attrs["password"]
        user = authenticate_by_identifier(identifier, password)

        if user is None:
            raise serializers.ValidationError("Invalid credentials.")

        profile = ensure_user_profile(user)
        if not (user.is_superuser or user.is_staff or profile.role in {UserProfile.Role.ADMIN, UserProfile.Role.LIBRARIAN}):
            raise serializers.ValidationError("This account does not have library admin access.")

        token, _ = Token.objects.get_or_create(user=user)
        attrs["user"] = user
        attrs["profile"] = profile
        attrs["token"] = token
        return attrs


class StudentRegistrationSerializer(serializers.Serializer):
    fullName = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8, max_length=128)
    phoneNumber = serializers.CharField(source="phone_number", max_length=30, allow_blank=True, required=False)
    studentIdCode = serializers.CharField(source="student_id_code", max_length=40, allow_blank=True, required=False)

    def validate_email(self, value: str) -> str:
        normalized = value.strip().lower()
        if User.objects.filter(email__iexact=normalized).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        if User.objects.filter(username__iexact=normalized).exists():
            raise serializers.ValidationError("This email address is already being used as a username.")
        return normalized

    def validate_fullName(self, value: str) -> str:
        normalized = " ".join(value.strip().split())
        if len(normalized) < 3:
            raise serializers.ValidationError("Please enter your full name.")
        return normalized

    def create(self, validated_data):
        full_name = validated_data["fullName"]
        email = validated_data["email"]
        phone_number = validated_data.get("phone_number", "")
        student_id_code = validated_data.get("student_id_code", "")
        password = validated_data["password"]
        first_name, last_name = split_full_name(full_name)

        user = User.objects.create_user(
            username=email,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
        )
        profile = ensure_user_profile(user)
        profile.role = UserProfile.Role.STUDENT
        profile.phone_number = phone_number
        profile.student_id_code = student_id_code
        profile.save(update_fields=["role", "phone_number", "student_id_code", "updated_at"])
        return user


class UserProfileUpdateSerializer(serializers.Serializer):
    fullName = serializers.CharField(max_length=150)
    phoneNumber = serializers.CharField(source="phone_number", max_length=30, allow_blank=True, required=False)
    studentIdCode = serializers.CharField(source="student_id_code", max_length=40, allow_blank=True, required=False)

    def validate_fullName(self, value: str) -> str:
        normalized = " ".join(value.strip().split())
        if len(normalized) < 3:
            raise serializers.ValidationError("Please enter your full name.")
        return normalized

    def update(self, instance: UserProfile, validated_data):
        full_name = validated_data.get("fullName", instance.user.get_full_name() or instance.user.get_username())
        first_name, last_name = split_full_name(full_name)

        user = instance.user
        user.first_name = first_name
        user.last_name = last_name
        user.save(update_fields=["first_name", "last_name"])

        instance.phone_number = validated_data.get("phone_number", instance.phone_number)
        instance.student_id_code = validated_data.get("student_id_code", instance.student_id_code)
        instance.save(update_fields=["phone_number", "student_id_code", "updated_at"])
        return instance


class StudentDashboardSerializer(serializers.Serializer):
    user = UserProfileSerializer()
    loans = LoanSerializer(many=True)
    requests = BookRequestSerializer(many=True)
    supportMessages = SupportMessageSerializer(many=True)


class LoanEmailSerializer(serializers.Serializer):
    subject = serializers.CharField(max_length=150)
    message = serializers.CharField(max_length=5000)
