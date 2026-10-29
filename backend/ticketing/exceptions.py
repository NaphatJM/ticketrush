from rest_framework import status
from rest_framework.exceptions import APIException


class SoldOut(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = 'Not enough tickets left for this request.'
    default_code = 'sold_out'


class SaleNotOpen(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = 'The sale for this event is not open.'
    default_code = 'sale_not_open'


class PerUserLimit(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = 'This request exceeds the per-user ticket limit for this event.'
    default_code = 'per_user_limit'


class HoldNotActive(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = 'This hold is no longer active.'
    default_code = 'hold_not_active'


class HoldHasOrder(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = 'This hold has an order and can no longer be released.'
    default_code = 'hold_has_order'


class SalesPaused(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = 'Ticket sales are paused. Try again shortly.'
    default_code = 'sales_paused'
