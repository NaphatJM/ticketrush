from drf_spectacular.utils import OpenApiParameter
from drf_spectacular.utils import extend_schema
from drf_spectacular.utils import extend_schema_view
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response

from reliability.services import run_idempotent
from utils.drf_helper.schema import ERROR_RESPONSE
from utils.drf_helper.schema import wrap_success
from utils.drf_helper.views import APIView
from utils.drf_helper.views import ListAPIView
from utils.drf_helper.views import RetrieveAPIView
from utils.drf_helper.views import encapsulation_result

from . import services
from .models import Event
from .serializers import EventSerializer
from .serializers import HoldCreateSerializer
from .serializers import HoldSerializer
from .throttles import HoldIPThrottle
from .throttles import HoldUserThrottle


IDEMPOTENCY_KEY_PARAMETER = OpenApiParameter(
    'Idempotency-Key',
    str,
    OpenApiParameter.HEADER,
    required=True,
    description='1 to 128 visible ASCII characters, unique per intended action. Retrying with the same key and body returns the first result.',
)
IDEMPOTENT_REPLAYED_HEADER = OpenApiParameter(
    'Idempotent-Replayed',
    str,
    OpenApiParameter.HEADER,
    enum=['true', 'false'],
    response=True,
    description='`true` when this response replays the result stored for the Idempotency-Key.',
)
IDEMPOTENCY_ERRORS_DESCRIPTION = (
    'A missing or malformed key returns `400 IDEMPOTENCY_KEY_REQUIRED`; the same key with a different body returns `422 IDEMPOTENCY_KEY_REUSED`; '
    'a key whose first request is still running returns `409 IN_PROGRESS`.'
)


@extend_schema_view(
    get=extend_schema(
        tags=['Events'],
        summary='List events',
        description='Public. `available` is the live stock count; prices are in satang (1/100 THB).',
        responses={200: EventSerializer(many=True)},
    )
)
class EventListView(ListAPIView):
    permission_classes = (AllowAny,)
    serializer_class = EventSerializer
    queryset = Event.objects.all()


@extend_schema_view(
    get=extend_schema(
        tags=['Events'],
        summary='Get an event',
        description='Public. `available` is the live stock count; prices are in satang (1/100 THB).',
        responses={200: wrap_success('EventDetail', EventSerializer()), 404: ERROR_RESPONSE},
    )
)
class EventDetailView(RetrieveAPIView):
    permission_classes = (AllowAny,)
    serializer_class = EventSerializer
    queryset = Event.objects.all()
    lookup_field = 'uuid'


class HoldCreateView(APIView):
    throttle_classes = (HoldUserThrottle, HoldIPThrottle)

    @extend_schema(
        tags=['Holds'],
        summary='Hold tickets',
        description='Reserves `quantity` tickets for the caller until `expires_at`. Stock is taken atomically, so tickets are never oversold. '
        "Errors: `409 SOLD_OUT`, `409 SALE_NOT_OPEN`, `409 PER_USER_LIMIT` (counts the caller's active and converted holds). "
        + IDEMPOTENCY_ERRORS_DESCRIPTION
        + ' Throttled per user and per client IP; `503 SALES_PAUSED` means the throttle store is down and sales are paused.',
        request=HoldCreateSerializer,
        parameters=[IDEMPOTENCY_KEY_PARAMETER, IDEMPOTENT_REPLAYED_HEADER],
        responses={
            201: wrap_success('HoldCreated', HoldSerializer()),
            400: ERROR_RESPONSE,
            401: ERROR_RESPONSE,
            404: ERROR_RESPONSE,
            409: ERROR_RESPONSE,
            422: ERROR_RESPONSE,
            429: ERROR_RESPONSE,
            503: ERROR_RESPONSE,
        },
    )
    def post(self, request: Request, uuid) -> Response:
        serializer = HoldCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        quantity = serializer.validated_data['quantity']

        def action():
            hold = services.create_hold(user=request.user, event_uuid=uuid, quantity=quantity)
            return status.HTTP_201_CREATED, HoldSerializer(hold).data

        result = run_idempotent(
            user=request.user,
            key=request.headers.get('Idempotency-Key'),
            endpoint='events.holds.create',
            payload={'event': str(uuid), 'quantity': quantity},
            action=action,
        )
        return Response(encapsulation_result(result.body), status=result.status_code, headers={'Idempotent-Replayed': str(result.replayed).lower()})


class HoldReleaseView(APIView):
    @extend_schema(
        tags=['Holds'],
        summary='Release a hold',
        description='Returns the held tickets to stock. Only an active hold without an order can be released: '
        "otherwise `409 HOLD_NOT_ACTIVE` or `409 HOLD_HAS_ORDER`. Another user's hold returns `404 NOT_FOUND`.",
        responses={200: wrap_success('HoldReleased', HoldSerializer()), 401: ERROR_RESPONSE, 404: ERROR_RESPONSE, 409: ERROR_RESPONSE},
    )
    def delete(self, request: Request, uuid) -> Response:
        hold = services.release_hold(user=request.user, hold_uuid=uuid)
        return Response(encapsulation_result(HoldSerializer(hold).data))
