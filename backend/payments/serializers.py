from rest_framework import serializers

from ticketing.models import Order

from .models import Payment
from .models import Ticket


class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = ('uuid', 'status', 'amount_satang', 'payment_url', 'expires_at')
        read_only_fields = fields


class OrderSerializer(serializers.ModelSerializer):
    hold = serializers.UUIDField(source='hold.uuid', read_only=True)
    event = serializers.UUIDField(source='hold.event.uuid', read_only=True)
    quantity = serializers.IntegerField(source='hold.quantity', read_only=True)
    payment = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = ('uuid', 'hold', 'event', 'quantity', 'amount_satang', 'status', 'paid_at', 'created_on', 'payment')
        read_only_fields = fields

    def get_payment(self, order: Order) -> dict | None:
        payment = order.payments.order_by('-id').first()
        return PaymentSerializer(payment).data if payment is not None else None


class TicketEventSerializer(serializers.Serializer):
    uuid = serializers.UUIDField()
    title = serializers.CharField()
    starts_at = serializers.DateTimeField()


class TicketSerializer(serializers.ModelSerializer):
    order = serializers.UUIDField(source='order.uuid', read_only=True)
    event = TicketEventSerializer(source='order.hold.event', read_only=True)

    class Meta:
        model = Ticket
        fields = ('uuid', 'order', 'event', 'seq', 'code', 'issued_at')
        read_only_fields = fields
