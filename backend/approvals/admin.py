from django.contrib import admin

from approvals.models import ApprovalRequest, ApprovalDecision


@admin.register(ApprovalRequest)
class ApprovalRequestAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "invoice",
        "organization",
        "submitted_by",
        "status",
        "created_at",
    )

    list_filter = (
        "status",
        "organization",
        "created_at",
    )

    search_fields = (
        "invoice__invoice_number",
        "submitted_by__username",
        "organization__name",
    )

    readonly_fields = (
        "id",
        "created_at",
        "updated_at",
    )


@admin.register(ApprovalDecision)
class ApprovalDecisionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "approval_request",
        "decided_by",
        "outcome",
        "decided_at",
    )

    list_filter = (
        "outcome",
        "decided_at",
    )

    search_fields = (
        "approval_request__invoice__invoice_number",
        "decided_by__username",
    )

    readonly_fields = (
        "id",
        "approval_request",
        "decided_by",
        "outcome",
        "comment",
        "decided_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False