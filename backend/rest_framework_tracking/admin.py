from django.contrib import admin

from .models import APIRequestLog


@admin.register(APIRequestLog)
class APIRequestLogAdmin(admin.ModelAdmin):
    date_hierarchy = 'requested_at'
    list_display = ('requested_at', 'method', 'path', 'status_code', 'response_ms', 'username_persistent', 'cid')
    list_filter = ('method', 'status_code')
    search_fields = ('path', 'username_persistent', 'cid')
    raw_id_fields = ('user',)

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False
