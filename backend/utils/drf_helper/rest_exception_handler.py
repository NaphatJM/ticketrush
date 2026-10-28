import logging
from typing import Any

from django.core.exceptions import PermissionDenied
from django.http import Http404
from rest_framework import exceptions
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import set_rollback

from .constants import CODE_BAD_REQUEST
from .constants import CODE_FORBIDDEN
from .constants import CODE_INTERNAL_SERVER_ERROR
from .constants import CODE_NOT_AUTHENTICATED
from .constants import CODE_NOT_FOUND
from .constants import MESSAGE_BAD_REQUEST
from .constants import MESSAGE_FORBIDDEN
from .constants import MESSAGE_INTERNAL_SERVER_ERROR
from .constants import MESSAGE_NOT_AUTHENTICATED
from .constants import MESSAGE_NOT_FOUND


logger = logging.getLogger(__name__)


def _error_body(code: str, message, trace: dict | None = None) -> dict[str, Any]:
    return {'status': {'code': code, 'message': str(message)}, 'trace': trace or {}}


def handle_validation_error(exc: exceptions.ValidationError) -> Response:
    """Flatten field errors into `[field] message` lines."""
    error_messages: list[str] = []
    if isinstance(exc.detail, dict):
        for key, val in exc.detail.items():
            if isinstance(val, list):
                error_messages.extend(f'[{key}] {error_val}' for error_val in val)
            else:
                error_messages.append(f'[{key}] {val}')
    elif isinstance(exc.detail, list):
        error_messages = [str(item) for item in exc.detail]

    if error_messages:
        message = '\n'.join(error_messages)
    elif isinstance(exc.detail, list | dict):
        message = MESSAGE_BAD_REQUEST
    else:
        message = str(exc.detail) or MESSAGE_BAD_REQUEST
    set_rollback()
    return Response(_error_body(CODE_BAD_REQUEST, message), status=status.HTTP_400_BAD_REQUEST)


def handle_not_authenticated(exc: Exception) -> Response:
    headers: dict[str, str] = {}
    auth_header = getattr(exc, 'auth_header', None)
    if auth_header:
        headers['WWW-Authenticate'] = str(auth_header)
    set_rollback()
    return Response(_error_body(CODE_NOT_AUTHENTICATED, MESSAGE_NOT_AUTHENTICATED), status=status.HTTP_401_UNAUTHORIZED, headers=headers)


def handle_permission_denied() -> Response:
    set_rollback()
    return Response(_error_body(CODE_FORBIDDEN, MESSAGE_FORBIDDEN), status=status.HTTP_403_FORBIDDEN)


def handle_api_exception(exc: exceptions.APIException) -> Response:
    """Domain errors: `default_code` becomes `status.code`, and `exc.trace` carries structured data."""
    headers: dict[str, str] = {}
    if getattr(exc, 'auth_header', None):
        headers['WWW-Authenticate'] = exc.auth_header
    if getattr(exc, 'wait', None):
        headers['Retry-After'] = str(exc.wait)
    code = getattr(exc, 'default_code', CODE_INTERNAL_SERVER_ERROR).upper()
    body = _error_body(code, exc.detail, getattr(exc, 'trace', None))
    set_rollback()
    logger.info('api exception', extra={'code': code, 'http_status': exc.status_code})
    return Response(body, status=exc.status_code, headers=headers)


def handle_404() -> Response:
    set_rollback()
    return Response(_error_body(CODE_NOT_FOUND, MESSAGE_NOT_FOUND), status=status.HTTP_404_NOT_FOUND)


def handle_unseen_error(exc: Exception) -> Response:
    set_rollback()
    logger.error('unhandled exception', exc_info=exc)
    return Response(_error_body(CODE_INTERNAL_SERVER_ERROR, MESSAGE_INTERNAL_SERVER_ERROR), status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def exception_handler(exc: Exception, context) -> Response:
    if isinstance(exc, exceptions.ValidationError):
        return handle_validation_error(exc)
    if isinstance(exc, exceptions.NotAuthenticated | exceptions.AuthenticationFailed):
        return handle_not_authenticated(exc)
    if isinstance(exc, PermissionDenied | exceptions.PermissionDenied):
        return handle_permission_denied()
    if isinstance(exc, exceptions.APIException):
        return handle_api_exception(exc)
    if isinstance(exc, Http404):
        return handle_404()
    return handle_unseen_error(exc)
