from rest_framework import status
from rest_framework.exceptions import APIException


class PaymentsUnavailable(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = 'Payments are temporarily unavailable. Your hold is kept until it expires.'
    default_code = 'payments_unavailable'


class HoldExpiringSoon(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = 'This hold expires too soon to start a payment.'
    default_code = 'hold_expiring'


class OrderNotPayable(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = 'This order can no longer be paid.'
    default_code = 'order_not_payable'


class InvalidWebhookSignature(APIException):
    status_code = status.HTTP_401_UNAUTHORIZED
    default_detail = 'The webhook signature is missing, invalid, or outside the time tolerance.'
    default_code = 'invalid_signature'
