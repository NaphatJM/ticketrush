import logging
import time
import traceback

from django.conf import settings
from django_guid import get_guid
from rest_framework.permissions import SAFE_METHODS

from audit.middleware import get_client_ip

from .models import APIRequestLog


logger = logging.getLogger(__name__)

SENSITIVE_FIELDS = frozenset({'password', 'old_password', 'new_password', 'token', 'access', 'refresh', 'secret', 'key', 'signature'})
CLEANED_SUBSTITUTE = '********'
_MAX_PATH = APIRequestLog._meta.get_field('path').max_length
_MAX_USER_AGENT = APIRequestLog._meta.get_field('user_agent').max_length


class TrackingMixin:
    """Store a request row for every write, every error, and every slow request.

    Successful fast reads are skipped so a flash sale's browse traffic does not double the write load.
    """

    #: Added to SENSITIVE_FIELDS, never a replacement for it.
    tracking_sensitive_fields: frozenset[str] = frozenset()

    def initial(self, request, *args, **kwargs):
        self._tracking_started = time.monotonic()
        self._tracking_errors = ''
        super().initial(request, *args, **kwargs)

    def handle_exception(self, exc):
        response = super().handle_exception(exc)
        if response.status_code >= 500:
            self._tracking_errors = traceback.format_exc()
        return response

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        started = getattr(self, '_tracking_started', None)
        response_ms = int((time.monotonic() - started) * 1000) if started is not None else 0
        if self.should_track(request, response, response_ms):
            try:
                self._save_log(request, response, response_ms)
            except Exception:
                logger.exception('failed to store API request log', extra={'path': request.path})
        return response

    def should_track(self, request, response, response_ms: int) -> bool:
        return request.method not in SAFE_METHODS or response.status_code >= 400 or response_ms >= settings.DRF_TRACKING_SLOW_MS

    def _save_log(self, request, response, response_ms: int) -> None:
        user = getattr(request, 'user', None)
        authenticated = bool(user and user.is_authenticated)
        APIRequestLog.objects.create(
            user=user if authenticated else None,
            username_persistent=user.get_username() if authenticated else '',
            response_ms=response_ms,
            path=request.path[:_MAX_PATH],
            view=f'{type(self).__module__}.{type(self).__name__}',
            method=request.method,
            status_code=response.status_code,
            remote_addr=get_client_ip(),
            host=request.get_host(),
            user_agent=request.headers.get('user-agent', '')[:_MAX_USER_AGENT],
            query_params=self._clean(dict(request.query_params)),
            data=self._clean(self._request_data(request)),
            response=self._clean(getattr(response, 'data', None)) if response.status_code >= 400 else None,
            errors=self._tracking_errors,
            cid=get_guid() or '',
        )

    @staticmethod
    def _request_data(request):
        try:
            data = request.data
        except Exception:
            return None
        return data.dict() if hasattr(data, 'dict') else data

    def _clean(self, data):
        blocked = SENSITIVE_FIELDS | self.tracking_sensitive_fields
        if isinstance(data, dict):
            return {key: CLEANED_SUBSTITUTE if str(key).lower() in blocked else self._clean(value) for key, value in data.items()}
        if isinstance(data, list):
            return [self._clean(item) for item in data]
        return data
