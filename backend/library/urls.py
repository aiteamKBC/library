from rest_framework.routers import DefaultRouter

from django.urls import path
from . import lms_sso

from .views import (
    AdminLoginView,
    AdminLogoutView,
    AuthMeView,
    BookCopyViewSet,
    BookFeedbackViewSet,
    BookRequestViewSet,
    CategoryViewSet,
    LoanViewSet,
    ResourceViewSet,
    StudentDashboardView,
    StudentLoginView,
    SupportMessageViewSet,
    TimezoneObservationView,
    TimezonePreferenceView,
)

router = DefaultRouter()
router.register("categories", CategoryViewSet, basename="category")
router.register("resources", ResourceViewSet, basename="resource")
router.register("copies", BookCopyViewSet, basename="copy")
router.register("feedback", BookFeedbackViewSet, basename="feedback")
router.register("loans", LoanViewSet, basename="loan")
router.register("requests", BookRequestViewSet, basename="request")
router.register("support-messages", SupportMessageViewSet, basename="support-message")

urlpatterns = [
    path("auth/lms/start/", lms_sso.start, name="lms-sso-start"),
    path("auth/lms/exchange/", lms_sso.ExchangeView.as_view(), name="lms-sso-exchange"),
    path("auth/login/", AdminLoginView.as_view(), name="auth-login"),
    path("auth/student-login/", StudentLoginView.as_view(), name="auth-student-login"),
    path("auth/me/", AuthMeView.as_view(), name="auth-me"),
    path("auth/timezone-observation/", TimezoneObservationView.as_view(), name="auth-timezone-observation"),
    path("auth/timezone-preference/", TimezonePreferenceView.as_view(), name="auth-timezone-preference"),
    path("auth/dashboard/", StudentDashboardView.as_view(), name="auth-dashboard"),
    path("auth/logout/", AdminLogoutView.as_view(), name="auth-logout"),
    *router.urls,
]
