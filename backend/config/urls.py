from django.contrib import admin
from django.urls import path, include
from config.auth_views import (
    CSRFTokenAPIView,
    LoginAPIView,
    LogoutAPIView,
    CurrentUserAPIView,
)

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("documents.urls")),
    path("api/", include("invoices.urls")),
    path("api/", include("approvals.urls")),
    path(
        "api/auth/csrf/",
        CSRFTokenAPIView.as_view(),
        name="auth-csrf",
    ),
    path(
        "api/auth/login/",
        LoginAPIView.as_view(),
        name="auth-login",
    ),
    path(
        "api/auth/logout/",
        LogoutAPIView.as_view(),
        name="auth-logout",
    ),
    path(
        "api/auth/me/",
        CurrentUserAPIView.as_view(),
        name="auth-me",
    ),
    path("api/", include("vendors.urls")),
    path("api/", include("accounting.urls")),
]