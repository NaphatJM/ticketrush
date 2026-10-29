import logging

from redis.exceptions import RedisError
from rest_framework.throttling import SimpleRateThrottle

from audit.middleware import resolve_client_ip

from .exceptions import SalesPaused


logger = logging.getLogger(__name__)


class FailClosedThrottle(SimpleRateThrottle):
    """A throttle store outage refuses the request: without it nothing limits a flood of new holds."""

    def allow_request(self, request, view) -> bool:
        try:
            return super().allow_request(request, view)
        except RedisError as exc:
            logger.error('throttle store unavailable', extra={'scope': self.scope}, exc_info=exc)
            raise SalesPaused from exc


class HoldUserThrottle(FailClosedThrottle):
    scope = 'holds_user'

    def get_cache_key(self, request, view) -> str | None:
        if not request.user.is_authenticated:
            return None
        return self.cache_format % {'scope': self.scope, 'ident': request.user.pk}


class HoldIPThrottle(FailClosedThrottle):
    scope = 'holds_ip'

    def get_cache_key(self, request, view) -> str | None:
        return self.cache_format % {'scope': self.scope, 'ident': resolve_client_ip(request._request)}
