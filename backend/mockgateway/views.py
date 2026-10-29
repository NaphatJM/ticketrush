from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response

from utils.drf_helper.views import APIView
from utils.drf_helper.views import encapsulation_result

from . import services
from .serializers import MockChargeSerializer
from .serializers import PaySerializer


class GatewayView(APIView):
    """The provider's own pages: they authenticate nobody, and the unguessable charge id is the capability."""

    authentication_classes = ()
    permission_classes = (AllowAny,)


class ChargeDetailView(GatewayView):
    @extend_schema(responses={200: MockChargeSerializer})
    def get(self, request: Request, charge_id: str) -> Response:
        return Response(encapsulation_result(MockChargeSerializer(services.get_charge(charge_id)).data))


class ChargePayView(GatewayView):
    @extend_schema(request=PaySerializer, responses={200: MockChargeSerializer})
    def post(self, request: Request, charge_id: str) -> Response:
        serializer = PaySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        charge = services.pay(charge_id=charge_id, succeed=serializer.validated_data['outcome'] == 'succeeded')
        return Response(encapsulation_result(MockChargeSerializer(charge).data))
