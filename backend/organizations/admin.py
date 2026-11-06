from django.contrib import admin

from organizations.models import (
    Organization,
    OrganizationMembership,
)


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):

    list_display = (
        "name",
        "slug",
        "default_currency",
        "is_active",
        "created_at",
    )

    search_fields = ("name", "legal_name", "slug")
    list_filter = ("is_active", "default_currency")


@admin.register(OrganizationMembership)
class OrganizationMembershipAdmin(admin.ModelAdmin):

    list_display = (
        "user",
        "organization",
        "role",
        "is_active",
    )

    list_filter = ("role", "is_active")
    search_fields = (
        "user__username",
        "organization__name",
    )