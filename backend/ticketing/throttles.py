from audit.middleware import resolve_client_ip
from utils.drf_helper.throttling import FailClosedThrottle

from .exceptions import SalesPaused


class HoldUserThrottle(FailClosedThrottle):
    scope = 'holds_user'
    outage_exception = SalesPaused

    def get_cache_key(self, request, view) -> str | None:
        if not request.user.is_authenticated:
            return None
        return self.cache_format % {'scope': self.scope, 'ident': request.user.pk}


class HoldIPThrottle(FailClosedThrottle):
    scope = 'holds_ip'
    outage_exception = SalesPaused

    def get_cache_key(self, request, view) -> str | None:
        return self.cache_format % {'scope': self.scope, 'ident': resolve_client_ip(request._request)}
