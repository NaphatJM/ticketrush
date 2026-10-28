import logging
from typing import ClassVar


REDACTED_FIELDS = frozenset({'password', 'old_password', 'new_password', 'token', 'access', 'refresh', 'secret', 'authorization', 'signature'})
REDACTED_SUBSTITUTE = '********'


class LoggingMixin:
    """Log every response: 5xx at ERROR, 4xx at WARNING, the rest at DEBUG."""

    #: Added to REDACTED_FIELDS, never a replacement for it.
    sensitive_fields: ClassVar[frozenset[str]] = frozenset()

    def _logger(self) -> logging.Logger:
        return logging.getLogger(type(self).__module__)

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        status_code = getattr(response, 'status_code', 0)
        if status_code >= 500:
            level = logging.ERROR
        elif status_code >= 400:
            level = logging.WARNING
        else:
            level = logging.DEBUG
        logger = self._logger()
        if logger.isEnabledFor(level):
            logger.log(level, 'response', extra={'http_method': request.method, 'path': request.path, 'http_status': status_code})
        return response

    def redact(self, payload):
        blocked = REDACTED_FIELDS | self.sensitive_fields
        if isinstance(payload, dict):
            return {key: REDACTED_SUBSTITUTE if str(key).lower() in blocked else self.redact(value) for key, value in payload.items()}
        if isinstance(payload, list):
            return [self.redact(item) for item in payload]
        return payload
