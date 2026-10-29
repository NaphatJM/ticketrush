from rest_framework import status
from rest_framework.exceptions import APIException


class UsernameTaken(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = 'This username is already taken.'
    default_code = 'username_taken'


class SignInPaused(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = 'Signing in is paused. Try again shortly.'
    default_code = 'sign_in_paused'
