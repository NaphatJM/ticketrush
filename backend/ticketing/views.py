from drf_spectacular.utils import OpenApiParameter
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response

from reliability.services import run_idempotent
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


IDEMPOTENCY_KEY_PARAMETER = OpenApiParameter('Idempotency-Key', str, OpenApiParameter.HEADER, required=True)


class EventListView(ListAPIView):
    permission_classes = (AllowAny,)
    serializer_class = EventSerializer
    queryset = Event.objects.all()


class EventDetailView(RetrieveAPIView):
    permission_classes = (AllowAny,)
    serializer_class = EventSerializer
    queryset = Event.objects.all()
    lookup_field = 'uuid'


class HoldCreateView(APIView):
    throttle_classes = (HoldUserThrottle, HoldIPThrottle)

    @extend_schema(request=HoldCreateSerializer, responses={201: HoldSerializer}, parameters=[IDEMPOTENCY_KEY_PARAMETER])
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
    @extend_schema(responses={200: HoldSerializer})
    def delete(self, request: Request, uuid) -> Response:
        hold = services.release_hold(user=request.user, hold_uuid=uuid)
        return Response(encapsulation_result(HoldSerializer(hold).data))
