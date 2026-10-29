from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework_simplejwt.exceptions import InvalidToken
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.serializers import TokenRefreshSerializer

from utils.drf_helper.schema import ERROR_RESPONSE
from utils.drf_helper.schema import wrap_success
from utils.drf_helper.views import APIView
from utils.drf_helper.views import encapsulation_result

from . import services
from .models import User
from .serializers import RegisterResponseSerializer
from .serializers import RegisterSerializer
from .serializers import TokenObtainPairSerializer
from .serializers import TokenPairSerializer
from .serializers import UserSerializer
from .throttles import AuthIPThrottle
from .throttles import LoginUsernameThrottle


class AnonymousAuthView(APIView):
    # No authentication: a stale or broken access token must not block signing in again.
    authentication_classes = ()
    permission_classes = (AllowAny,)


class RegisterView(AnonymousAuthView):
    throttle_classes = (AuthIPThrottle,)

    @extend_schema(
        tags=['Auth'],
        summary='Register a buyer account',
        description='Creates a buyer and returns the user with a token pair, so the client is signed in at once. '
        'Usernames are unique; a taken name returns `409 USERNAME_TAKEN`. '
        'Throttled per client IP; `503 SIGN_IN_PAUSED` means the throttle store is down and sign-up is paused.',
        request=RegisterSerializer,
        responses={
            201: wrap_success('Register', RegisterResponseSerializer()),
            400: ERROR_RESPONSE,
            409: ERROR_RESPONSE,
            429: ERROR_RESPONSE,
            503: ERROR_RESPONSE,
        },
    )
    def post(self, request: Request) -> Response:
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = services.register_user(**serializer.validated_data)
        refresh = TokenObtainPairSerializer.get_token(user)
        data = {'user': UserSerializer(user).data, 'access': str(refresh.access_token), 'refresh': str(refresh)}
        return Response(encapsulation_result(data), status=status.HTTP_201_CREATED)


class LoginView(AnonymousAuthView):
    throttle_classes = (LoginUsernameThrottle, AuthIPThrottle)

    @extend_schema(
        tags=['Auth'],
        summary='Sign in',
        description='Returns an access token (15 minutes) and a refresh token (7 days). Send the access token as `Authorization: Bearer <token>`. '
        'Wrong credentials return `401 NOT_AUTHENTICATED` without saying which part was wrong. '
        'Throttled per username and per client IP; `503 SIGN_IN_PAUSED` means the throttle store is down.',
        request=TokenObtainPairSerializer,
        responses={
            200: wrap_success('Login', TokenPairSerializer()),
            400: ERROR_RESPONSE,
            401: ERROR_RESPONSE,
            429: ERROR_RESPONSE,
            503: ERROR_RESPONSE,
        },
    )
    def post(self, request: Request) -> Response:
        serializer = TokenObtainPairSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        return Response(encapsulation_result(serializer.validated_data))


class RefreshView(AnonymousAuthView):
    @extend_schema(
        tags=['Auth'],
        summary='Refresh the token pair',
        description='Returns a new access and refresh token. The submitted refresh token is blacklisted, so each one works once; '
        'a reused, expired, or forged token returns `401 NOT_AUTHENTICATED`.',
        request=TokenRefreshSerializer,
        responses={200: wrap_success('Refresh', TokenPairSerializer()), 400: ERROR_RESPONSE, 401: ERROR_RESPONSE},
    )
    def post(self, request: Request) -> Response:
        serializer = TokenRefreshSerializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except (TokenError, User.DoesNotExist) as exc:
            raise InvalidToken from exc
        return Response(encapsulation_result(serializer.validated_data))
