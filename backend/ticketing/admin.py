from django.contrib import admin
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from .models import Event
from .models import Hold
from .models import Order


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ('title', 'category', 'is_published', 'starts_at', 'sale_opens_at', 'sale_closes_at', 'capacity', 'available', 'price_satang')
    list_filter = ('is_published', 'category')
    search_fields = ('title', 'venue_name')
    readonly_fields = ('uuid', 'available', 'banner_preview')
    fieldsets = (
        (None, {'fields': ('uuid', 'organizer', 'title', 'is_published')}),
        (_('Listing'), {'fields': ('summary', 'category', 'presented_by', 'banner_url', 'banner_preview')}),
        (_('Details'), {'fields': ('description', 'important_info')}),
        (_('Schedule and venue'), {'fields': ('starts_at', 'ends_at', 'venue_name', 'venue_address', 'venue_map_url')}),
        (_('Sale'), {'fields': ('sale_opens_at', 'sale_closes_at', 'capacity', 'available', 'price_satang', 'max_per_user')}),
    )

    @admin.display(description=_('banner preview'))
    def banner_preview(self, obj: Event) -> str:
        if not obj.banner_url:
            return '-'
        return format_html('<img src="{}" alt="" style="max-width:480px;max-height:240px;border-radius:6px">', obj.banner_url)

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
