from rest_framework.routers import DefaultRouter

from django.urls import path

from .views import (
    AdminLoginView,
    AdminLogoutView,
    AuthMeView,
    BookCopyViewSet,
    BookRequestViewSet,
    CategoryViewSet,
    LoanViewSet,
    ResourceViewSet,
    SupportMessageViewSet,
)

router = DefaultRouter()
router.register("categories", CategoryViewSet, basename="category")
router.register("resources", ResourceViewSet, basename="resource")
router.register("copies", BookCopyViewSet, basename="copy")
router.register("loans", LoanViewSet, basename="loan")
router.register("requests", BookRequestViewSet, basename="request")
router.register("support-messages", SupportMessageViewSet, basename="support-message")

urlpatterns = [
    path("auth/login/", AdminLoginView.as_view(), name="auth-login"),
    path("auth/me/", AuthMeView.as_view(), name="auth-me"),
    path("auth/logout/", AdminLogoutView.as_view(), name="auth-logout"),
    *router.urls,
]
