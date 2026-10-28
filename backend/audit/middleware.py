from collections.abc import Callable
from contextvars import ContextVar

from django.conf import settings
from django.http import HttpRequest
from django.http import HttpResponse


_client_ip: ContextVar[str] = ContextVar('audit_client_ip', default='')


def get_client_ip() -> str:
    return _client_ip.get()


def resolve_client_ip(request: HttpRequest) -> str:
    # X-Forwarded-For is client-controlled unless a trusted proxy overwrites it.
    if settings.TRUST_FORWARDED_FOR:
        forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
        if forwarded:
            return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '') or ''


def client_ip_middleware(get_response: Callable[[HttpRequest], HttpResponse]) -> Callable[[HttpRequest], HttpResponse]:
    """Expose the client IP to the service layer without passing the request down."""

    def middleware(request: HttpRequest) -> HttpResponse:
        token = _client_ip.set(resolve_client_ip(request))
        try:
            return get_response(request)
        finally:
            _client_ip.reset(token)

    return middleware
