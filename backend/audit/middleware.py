import hmac
import ipaddress
import logging
from collections.abc import Callable
from contextvars import ContextVar

from django.conf import settings
from django.http import HttpRequest
from django.http import HttpResponse


logger = logging.getLogger(__name__)

_client_ip: ContextVar[str] = ContextVar('audit_client_ip', default='')


def get_client_ip() -> str:
    return _client_ip.get()


def resolve_client_ip(request: HttpRequest) -> str:
    bff_client_ip = _bff_client_ip(request)
    if bff_client_ip:
        return bff_client_ip
    # X-Forwarded-For is client-controlled unless a trusted proxy overwrites it.
    if settings.TRUST_FORWARDED_FOR:
        forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
        if forwarded:
            return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '') or ''


def _bff_client_ip(request: HttpRequest) -> str:
    """The IP the frontend BFF saw, trusted only when the request carries the shared secret."""
    secret = settings.BFF_SHARED_SECRET
    sent = request.META.get('HTTP_BFF_SECRET', '')
    if not secret or not sent or not hmac.compare_digest(sent.encode(), secret.encode()):
        return ''
    raw = request.META.get('HTTP_BFF_CLIENT_IP', '').strip()
    try:
        return str(ipaddress.ip_address(raw))
    except ValueError:
        logger.warning('BFF-Client-IP ignored: not an IP address', extra={'value': raw[:64]})
        return ''


def client_ip_middleware(get_response: Callable[[HttpRequest], HttpResponse]) -> Callable[[HttpRequest], HttpResponse]:
    """Expose the client IP to the service layer without passing the request down."""

    def middleware(request: HttpRequest) -> HttpResponse:
        token = _client_ip.set(resolve_client_ip(request))
        try:
            return get_response(request)
        finally:
            _client_ip.reset(token)

    return middleware
