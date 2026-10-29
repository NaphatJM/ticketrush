from django.contrib import admin

from .models import IdempotencyRecord


@admin.register(IdempotencyRecord)
class IdempotencyRecordAdmin(admin.ModelAdmin):
    list_display = ('created_on', 'endpoint', 'user', 'key', 'state', 'response_status', 'expires_at')
    list_filter = ('endpoint', 'state')
    search_fields = ('key',)
    list_select_related = ('user',)

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False
