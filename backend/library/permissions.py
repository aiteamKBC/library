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
