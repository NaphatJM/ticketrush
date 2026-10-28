from django.contrib import admin

from .models import ActivityLog


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ('created_on', 'verb', 'actor_username', 'target_label', 'target_id', 'cid')
    list_filter = ('verb',)
    search_fields = ('actor_username', 'target_id', 'cid')
    date_hierarchy = 'created_on'

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False
