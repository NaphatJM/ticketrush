from django.contrib import admin

from .models import Event
from .models import Hold
from .models import Order


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ('title', 'sale_opens_at', 'sale_closes_at', 'capacity', 'available', 'price_satang')
    search_fields = ('title',)
    readonly_fields = ('uuid', 'available')

    def get_readonly_fields(self, request, obj=None):
        # Stock is moved only by conditional updates; editing capacity after creation would desync `available`.
        if obj is not None:
            return (*self.readonly_fields, 'capacity')
        return self.readonly_fields

    def save_model(self, request, obj, form, change):
        if not change:
            obj.available = obj.capacity
        super().save_model(request, obj, form, change)


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


@admin.register(Hold)
class HoldAdmin(ReadOnlyAdmin):
    list_display = ('uuid', 'event', 'user', 'quantity', 'status', 'expires_at')
    list_filter = ('status',)
    search_fields = ('uuid', 'user__username')
    list_select_related = ('event', 'user')


@admin.register(Order)
class OrderAdmin(ReadOnlyAdmin):
    list_display = ('uuid', 'hold', 'amount_satang', 'status', 'paid_at')
    list_filter = ('status',)
    search_fields = ('uuid',)
    list_select_related = ('hold',)
