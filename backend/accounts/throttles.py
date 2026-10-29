import hashlib

from rest_framework import serializers

from audit.middleware import resolve_client_ip
from utils.drf_helper.throttling import FailClosedThrottle

from .exceptions import SignInPaused


class LoginUsernameThrottle(FailClosedThrottle):
    """Limits password guesses against one account, whichever IPs they come from."""

    scope = 'login_username'
    outage_exception = SignInPaused

    def get_cache_key(self, request, view) -> str | None:
        raw = request.data.get('username') if hasattr(request.data, 'get') else None
        try:
            # Normalise exactly as the login serializer does, or padded and numeric variants get their own buckets.
            username = serializers.CharField().run_validation(raw)
        except serializers.ValidationError:
            return None
        ident = hashlib.sha256(username.casefold().encode()).hexdigest()
        return self.cache_format % {'scope': self.scope, 'ident': ident}


class AuthIPThrottle(FailClosedThrottle):
    scope = 'auth_ip'
    outage_exception = SignInPaused

    def get_cache_key(self, request, view) -> str | None:
        return self.cache_format % {'scope': self.scope, 'ident': resolve_client_ip(request._request)}
