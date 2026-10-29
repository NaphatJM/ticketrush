import logging

from redis.exceptions import RedisError
from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.throttling import SimpleRateThrottle


logger = logging.getLogger(__name__)


class ThrottleStoreUnavailable(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = 'Service temporarily unavailable. Try again shortly.'
    default_code = 'service_unavailable'


class FailClosedThrottle(SimpleRateThrottle):
    """A throttle store outage refuses the request with `outage_exception` instead of letting it through unlimited."""

    outage_exception: type[APIException] = ThrottleStoreUnavailable

    def allow_request(self, request, view) -> bool:
        try:
            return super().allow_request(request, view)
        except RedisError as exc:
            logger.error('throttle store unavailable', extra={'scope': self.scope}, exc_info=exc)
            raise self.outage_exception from exc
