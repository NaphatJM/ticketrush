from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from ticketing.models import Order
from ticketing.serializers import EventSummarySerializer

from .models import Payment
from .models import Ticket


class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = ('uuid', 'status', 'amount_satang', 'payment_url', 'expires_at')
        read_only_fields = fields


class OrderTicketSerializer(serializers.ModelSerializer):
    class Meta:
        model = Ticket
        fields = ('uuid', 'seq', 'code', 'issued_at')
        read_only_fields = fields


class OrderSerializer(serializers.ModelSerializer):
    hold = serializers.UUIDField(source='hold.uuid', read_only=True)
    event = EventSummarySerializer(source='hold.event', read_only=True)
    quantity = serializers.IntegerField(source='hold.quantity', read_only=True)
    payment = serializers.SerializerMethodField()
    tickets = OrderTicketSerializer(many=True, read_only=True)

    class Meta:
        model = Order
        fields = ('uuid', 'hold', 'event', 'quantity', 'amount_satang', 'status', 'paid_at', 'created_on', 'payment', 'tickets')
        read_only_fields = fields

    @extend_schema_field(PaymentSerializer(allow_null=True))
    def get_payment(self, order: Order) -> dict | None:
        # all() reads a prefetch when the view made one, so a list does not query per order.
        payment = max(order.payments.all(), key=lambda payment: payment.pk, default=None)
        return PaymentSerializer(payment).data if payment is not None else None


class TicketSerializer(serializers.ModelSerializer):
    order = serializers.UUIDField(source='order.uuid', read_only=True)
    event = EventSummarySerializer(source='order.hold.event', read_only=True)

    class Meta:
        model = Ticket
        fields = ('uuid', 'order', 'event', 'seq', 'code', 'issued_at')
        read_only_fields = fields
