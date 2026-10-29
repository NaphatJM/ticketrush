from rest_framework import status
from rest_framework.exceptions import APIException


class IdempotencyKeyRequired(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = 'An Idempotency-Key header of 1 to 128 visible ASCII characters is required.'
    default_code = 'idempotency_key_required'


class IdempotencyKeyReused(APIException):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    default_detail = 'This Idempotency-Key was already used with a different request.'
    default_code = 'idempotency_key_reused'


class IdempotencyInProgress(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = 'A request with this Idempotency-Key is still in progress.'
    default_code = 'in_progress'
