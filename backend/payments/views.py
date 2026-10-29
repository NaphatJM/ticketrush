from drf_spectacular.utils import extend_schema
from drf_spectacular.utils import extend_schema_view
from drf_spectacular.utils import inline_serializer
from rest_framework import serializers
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response

from reliability.services import run_idempotent_two_phase
from ticketing.models import Order
from ticketing.views import IDEMPOTENCY_ERRORS_DESCRIPTION
from ticketing.views import IDEMPOTENCY_KEY_PARAMETER
from ticketing.views import IDEMPOTENT_REPLAYED_HEADER
from utils.drf_helper.schema import ERROR_RESPONSE
from utils.drf_helper.schema import wrap_success
from utils.drf_helper.views import APIView
from utils.drf_helper.views import ListAPIView
from utils.drf_helper.views import RetrieveAPIView
from utils.drf_helper.views import encapsulation_result

from . import services
from .models import Ticket
from .serializers import OrderSerializer
from .serializers import TicketSerializer


class CheckoutView(APIView):
    @extend_schema(
        tags=['Orders'],
        summary='Check out a hold',
        description='Creates the order for an active hold and starts a payment; open `payment.payment_url` to pay. '
        'Retrying checkout for the same hold resumes the same order and payment, and after a failed payment it starts a new one. '
        'Errors: `409 HOLD_NOT_ACTIVE`, `409 HOLD_EXPIRING` (too little time left to pay), `409 ORDER_NOT_PAYABLE`, '
        '`503 PAYMENTS_UNAVAILABLE` (the gateway failed; the hold is kept, so retry). ' + IDEMPOTENCY_ERRORS_DESCRIPTION,
        request=None,
        parameters=[IDEMPOTENCY_KEY_PARAMETER, IDEMPOTENT_REPLAYED_HEADER],
        responses={
            201: wrap_success('CheckoutCreated', OrderSerializer()),
            400: ERROR_RESPONSE,
            401: ERROR_RESPONSE,
            404: ERROR_RESPONSE,
            409: ERROR_RESPONSE,
            422: ERROR_RESPONSE,
            503: ERROR_RESPONSE,
        },
    )
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


@extend_schema_view(
    get=extend_schema(
        tags=['Orders'],
        summary='Get an order',
        description='Poll this after paying: the order becomes `paid` once the gateway webhook is processed and the tickets are issued. '
        '`paid_unfulfilled` means the payment arrived after the stock was gone and an operator must resolve it. '
        "Another user's order returns `404 NOT_FOUND`.",
        responses={200: wrap_success('OrderDetail', OrderSerializer()), 401: ERROR_RESPONSE, 404: ERROR_RESPONSE},
    )
)
class OrderDetailView(RetrieveAPIView):
    serializer_class = OrderSerializer
    lookup_field = 'uuid'

    def get_queryset(self):
        return my_orders(self.request.user)


@extend_schema_view(
    get=extend_schema(
        tags=['Orders'],
        summary='List my orders',
        description="The caller's orders in every status, newest first, each with its latest payment and its tickets once paid.",
        responses={200: OrderSerializer(many=True), 401: ERROR_RESPONSE},
    )
)
class MyOrdersView(ListAPIView):
    serializer_class = OrderSerializer

    def get_queryset(self):
        return my_orders(self.request.user)


def my_orders(user):
    return Order.objects.filter(hold__user=user).select_related('hold__event').prefetch_related('payments', 'tickets').order_by('-created_on', '-id')


@extend_schema_view(
    get=extend_schema(
        tags=['Tickets'],
        summary='List my tickets',
        description='Tickets issued to the caller, newest first. `code` is the value encoded in the QR code sent by email.',
        responses={200: TicketSerializer(many=True), 401: ERROR_RESPONSE},
    )
)
class MyTicketsView(ListAPIView):
    serializer_class = TicketSerializer

    def get_queryset(self):
        return Ticket.objects.filter(order__hold__user=self.request.user).select_related('order__hold__event').order_by('-issued_at', 'seq')


# Authenticated by the provider's signature over the raw body, which is checked before anything is stored.
class WebhookView(APIView):
    authentication_classes = ()
    permission_classes = (AllowAny,)

    @extend_schema(
        tags=['Webhooks'],
        summary='Receive a payment webhook',
        description='Called by the payment provider, not by clients. The signature header is verified before anything is stored, '
        'and events are deduplicated by provider event ID, so a redelivered event returns 200 without being applied twice. '
        'Only providers enabled on the server are accepted; others return `404 NOT_FOUND`.',
        request=None,
        responses={
            200: wrap_success('WebhookReceived', inline_serializer(name='WebhookReceipt', fields={'received': serializers.BooleanField()})),
            401: ERROR_RESPONSE,
            404: ERROR_RESPONSE,
        },
    )
    def post(self, request: Request, provider: str) -> Response:
        services.receive_webhook(provider=provider, body=request.body, headers=request.headers)
        return Response(encapsulation_result({'received': True}))
