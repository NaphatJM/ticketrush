from django.contrib import admin

from ticketing.admin import ReadOnlyAdmin

from .models import Payment
from .models import Ticket
from .models import WebhookEvent


@admin.register(Payment)
class PaymentAdmin(ReadOnlyAdmin):
    list_display = ('uuid', 'order', 'provider', 'provider_charge_id', 'status', 'amount_satang', 'expires_at')
    list_filter = ('provider', 'status')
    search_fields = ('uuid', 'provider_charge_id')
    list_select_related = ('order',)


@admin.register(WebhookEvent)
class WebhookEventAdmin(ReadOnlyAdmin):
    list_display = ('received_at', 'provider', 'provider_event_id', 'event_type', 'processed_at')
    list_filter = ('provider', 'event_type', ('processed_at', admin.EmptyFieldListFilter))
    search_fields = ('provider_event_id', 'payment_key')


@admin.register(Ticket)
class TicketAdmin(ReadOnlyAdmin):
    list_display = ('uuid', 'order', 'seq', 'issued_at')
    search_fields = ('uuid', 'order__uuid')
    list_select_related = ('order',)
