from django.utils import timezone
from rest_framework import serializers

from .models import Event
from .models import Hold


class EventSerializer(serializers.ModelSerializer):
    sale_status = serializers.SerializerMethodField()

    class Meta:
        model = Event
        fields = (
            'uuid',
            'title',
            'summary',
            'category',
            'banner_url',
            'venue_name',
            'starts_at',
            'ends_at',
            'sale_opens_at',
            'sale_closes_at',
            'sale_status',
            'capacity',
            'available',
            'price_satang',
            'max_per_user',
        )
        read_only_fields = fields

    def get_sale_status(self, event: Event) -> Event.SaleStatus:
        return event.sale_status(self.context.get('now') or timezone.now())


class EventDetailSerializer(EventSerializer):
    class Meta(EventSerializer.Meta):
        fields = (*EventSerializer.Meta.fields, 'description', 'important_info', 'presented_by', 'venue_address', 'venue_map_url')
        read_only_fields = fields


class EventSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Event
        fields = ('uuid', 'title', 'banner_url', 'venue_name', 'starts_at', 'ends_at')
        read_only_fields = fields


class HoldCreateSerializer(serializers.Serializer):
    quantity = serializers.IntegerField(min_value=1, max_value=32767)


class HoldSerializer(serializers.ModelSerializer):
    event = serializers.UUIDField(source='event.uuid', read_only=True)

    class Meta:
        model = Hold
        fields = ('uuid', 'event', 'quantity', 'status', 'expires_at', 'created_on')
        read_only_fields = fields
