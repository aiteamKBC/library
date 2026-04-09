from django.contrib.auth import authenticate
from rest_framework.authtoken.models import Token
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .models import BookCopy, BookRequest, Category, Loan, Resource, SupportMessage, UserProfile, ensure_user_profile


class CategorySerializer(serializers.ModelSerializer):
    resourceCount = serializers.IntegerField(source="resources.count", read_only=True)

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
    coverImage = serializers.URLField(source="cover_image", allow_blank=True, required=False)
    infoLink = serializers.URLField(source="info_link", allow_blank=True, required=False)
    totalCopies = serializers.ReadOnlyField(source="total_copies")
    availableCopies = serializers.ReadOnlyField(source="available_copies")
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
            "totalCopies",
            "availableCopies",
            "availabilityStatus",
            "availabilityLabel",
            "expectedAvailableDate",
            "availabilityNote",
            "canBorrow",
            "canReserve",
        ]


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
    resourceId = serializers.CharField(write_only=True, required=False)
    requestedFrom = serializers.DateField(write_only=True, required=False)
    bookTitle = serializers.CharField(source="book_copy.resource.title", read_only=True)
    accessionNumber = serializers.CharField(source="book_copy.accession_number", read_only=True)
    availabilityStatus = serializers.CharField(source="book_copy.status", read_only=True)
    requestedAt = serializers.DateTimeField(source="requested_at", required=False)
    approvedAt = serializers.DateTimeField(source="approved_at", allow_null=True, required=False)
    borrowedAt = serializers.DateTimeField(source="borrowed_at", allow_null=True, required=False)
    dueDate = serializers.DateField(source="due_date", allow_null=True, required=False)
    returnedAt = serializers.DateTimeField(source="returned_at", allow_null=True, required=False)

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
            "bookTitle",
            "accessionNumber",
            "availabilityStatus",
            "status",
            "requestedAt",
            "approvedAt",
            "borrowedAt",
            "dueDate",
            "returnedAt",
            "notes",
        ]
        read_only_fields = ["bookTitle", "accessionNumber", "availabilityStatus"]

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
        requested_from = attrs.get("requestedFrom")
        book_copy = None

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
        return attrs

    def create(self, validated_data):
        validated_data.pop("resourceId", None)
        validated_data.pop("requestedFrom", None)
        try:
            return super().create(validated_data)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict if hasattr(exc, "message_dict") else exc.messages) from exc

    def update(self, instance, validated_data):
        validated_data.pop("resourceId", None)
        validated_data.pop("requestedFrom", None)
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


class AdminLoginSerializer(serializers.Serializer):
    identifier = serializers.CharField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        identifier = attrs["identifier"].strip()
        password = attrs["password"]

        user = authenticate(username=identifier, password=password)
        if user is None and "@" in identifier:
            from django.contrib.auth import get_user_model

            User = get_user_model()
            matched_user = User.objects.filter(email__iexact=identifier).first()
            if matched_user:
                user = authenticate(username=matched_user.get_username(), password=password)

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


class LoanEmailSerializer(serializers.Serializer):
    subject = serializers.CharField(max_length=150)
    message = serializers.CharField(max_length=5000)
