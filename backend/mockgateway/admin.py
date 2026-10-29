from django.contrib import admin

from .models import FaultConfig
from .models import MockCharge


@admin.register(FaultConfig)
class FaultConfigAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'latency_ms', 'error_rate', 'duplicate_webhook_rate', 'drop_webhook_rate', 'updated_on')

    def has_add_permission(self, request) -> bool:
        return not FaultConfig.objects.exists()

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


@admin.register(MockCharge)
class MockChargeAdmin(admin.ModelAdmin):
    list_display = ('charge_id', 'amount_satang', 'status', 'expires_at', 'created_on')
    list_filter = ('status',)
    search_fields = ('charge_id', 'idempotency_key')

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False
