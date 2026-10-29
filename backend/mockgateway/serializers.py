from rest_framework import serializers

from .models import MockCharge


class MockChargeSerializer(serializers.ModelSerializer):
    class Meta:
        model = MockCharge
        fields = ('charge_id', 'amount_satang', 'status', 'expires_at')
        read_only_fields = fields


class PaySerializer(serializers.Serializer):
    outcome = serializers.ChoiceField(choices=('succeeded', 'failed'))
