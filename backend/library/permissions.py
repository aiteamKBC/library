from django.conf import settings
from rest_framework.permissions import BasePermission

from .models import UserProfile, ensure_user_profile


class IsLibraryStaff(BasePermission):
    message = "You must be an authenticated library staff member to perform this action."

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser or user.is_staff:
            return True
        profile = ensure_user_profile(user)
        return profile.role in {UserProfile.Role.LIBRARIAN, UserProfile.Role.ADMIN}


class IsDashboardApiKey(BasePermission):
    message = "Invalid or missing API key."

    def has_permission(self, request, view):
        api_key = request.META.get("HTTP_X_API_KEY", "").strip()
        expected = getattr(settings, "DASHBOARD_API_KEY", "").strip()
        return bool(api_key and expected and api_key == expected)


class IsLibraryStaffOrApiKey(BasePermission):
    message = "Authentication required: staff account or valid API key."

    def has_permission(self, request, view):
        return (
            IsLibraryStaff().has_permission(request, view)
            or IsDashboardApiKey().has_permission(request, view)
        )
