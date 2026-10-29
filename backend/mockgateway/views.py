from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response

from utils.drf_helper.schema import ERROR_RESPONSE
from utils.drf_helper.schema import wrap_success
from utils.drf_helper.views import APIView
from utils.drf_helper.views import encapsulation_result

from . import services
from .serializers import MockChargeSerializer
from .serializers import PaySerializer


# The provider's own pages: they authenticate nobody, and the unguessable charge id is the capability.
class GatewayView(APIView):
    authentication_classes = ()
    permission_classes = (AllowAny,)


class ChargeDetailView(GatewayView):
    @extend_schema(
        tags=['Mock gateway'],
        summary='Get a mock charge',
        description='Part of the mock payment provider, enabled only when the server runs the mock gateway. '
        'The charge ID in `payment.payment_url` is the only credential.',
        responses={200: wrap_success('MockChargeDetail', MockChargeSerializer()), 404: ERROR_RESPONSE},
    )
    def get(self, request: Request, charge_id: str) -> Response:
        return Response(encapsulation_result(MockChargeSerializer(services.get_charge(charge_id)).data))


class ChargePayView(GatewayView):
    @extend_schema(
        tags=['Mock gateway'],
        summary='Pay or decline a mock charge',
        description='Settles the charge and sends a signed webhook to TicketRush, as a real provider would. '
        'Errors: `409 CHARGE_NOT_PENDING`, `409 CHARGE_EXPIRED`.',
        request=PaySerializer,
        responses={200: wrap_success('MockChargePaid', MockChargeSerializer()), 400: ERROR_RESPONSE, 404: ERROR_RESPONSE, 409: ERROR_RESPONSE},
    )
    def post(self, request: Request, charge_id: str) -> Response:
        serializer = PaySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        charge = services.pay(charge_id=charge_id, succeed=serializer.validated_data['outcome'] == 'succeeded')
        return Response(encapsulation_result(MockChargeSerializer(charge).data))
