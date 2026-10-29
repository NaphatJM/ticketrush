from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response

from reliability.services import run_idempotent_two_phase
from ticketing.models import Order
from ticketing.views import IDEMPOTENCY_KEY_PARAMETER
from utils.drf_helper.views import APIView
from utils.drf_helper.views import ListAPIView
from utils.drf_helper.views import RetrieveAPIView
from utils.drf_helper.views import encapsulation_result

from . import services
from .models import Ticket
from .serializers import OrderSerializer
from .serializers import TicketSerializer


class CheckoutView(APIView):
    @extend_schema(request=None, responses={201: OrderSerializer}, parameters=[IDEMPOTENCY_KEY_PARAMETER])
    def post(self, request: Request, uuid) -> Response:
        def perform(payment):
            payment = services.submit_charge(payment)
            return status.HTTP_201_CREATED, OrderSerializer(payment.order).data

        result = run_idempotent_two_phase(
            user=request.user,
            key=request.headers.get('Idempotency-Key'),
            endpoint='holds.checkout',
            payload={'hold': str(uuid)},
            prepare=lambda: services.prepare_checkout(user=request.user, hold_uuid=uuid),
            perform=perform,
        )
        return Response(encapsulation_result(result.body), status=result.status_code, headers={'Idempotent-Replayed': str(result.replayed).lower()})


class OrderDetailView(RetrieveAPIView):
    serializer_class = OrderSerializer
    lookup_field = 'uuid'

    def get_queryset(self):
        return Order.objects.filter(hold__user=self.request.user).select_related('hold__event')


class MyTicketsView(ListAPIView):
    serializer_class = TicketSerializer

    def get_queryset(self):
        return Ticket.objects.filter(order__hold__user=self.request.user).select_related('order__hold__event').order_by('-issued_at', 'seq')


class WebhookView(APIView):
    """Authenticated by the provider's signature over the raw body, which is checked before anything is stored."""

    authentication_classes = ()
    permission_classes = (AllowAny,)

    @extend_schema(request=None, responses={200: None})
    def post(self, request: Request, provider: str) -> Response:
        services.receive_webhook(provider=provider, body=request.body, headers=request.headers)
        return Response(encapsulation_result({'received': True}))
