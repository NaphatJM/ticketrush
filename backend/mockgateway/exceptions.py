from rest_framework import status
from rest_framework.exceptions import APIException


class GatewayError(Exception):
    """The provider refused or failed the call; the caller may retry with the same idempotency key."""


class GatewayTimeoutError(GatewayError):
    pass


class ChargeNotPending(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = 'This charge is no longer awaiting payment.'
    default_code = 'charge_not_pending'


class ChargeExpired(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = 'This charge expired before it was paid.'
    default_code = 'charge_expired'
