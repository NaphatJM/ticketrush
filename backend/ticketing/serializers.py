from rest_framework import serializers

from .models import Event
from .models import Hold


class EventSerializer(serializers.ModelSerializer):
    class Meta:
        model = Event
        fields = ('uuid', 'title', 'starts_at', 'sale_opens_at', 'sale_closes_at', 'capacity', 'available', 'price_satang', 'max_per_user')
        read_only_fields = fields


class HoldCreateSerializer(serializers.Serializer):
    quantity = serializers.IntegerField(min_value=1, max_value=32767)


class HoldSerializer(serializers.ModelSerializer):
    event = serializers.UUIDField(source='event.uuid', read_only=True)

    class Meta:
        model = Hold
        fields = ('uuid', 'event', 'quantity', 'status', 'expires_at', 'created_on')
        read_only_fields = fields
