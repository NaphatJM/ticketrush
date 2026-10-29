from django.db import IntegrityError
from django.db import transaction
from django.utils import timezone
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken

from audit.constants import ActivityVerb
from audit.services import log_action

from .exceptions import UsernameTaken
from .models import User


def register_user(*, username: str, email: str, password: str) -> User:
    """Create a buyer account. The unique index on username decides a race between two sign-ups."""
    try:
        with transaction.atomic():
            user = User.objects.create_user(username=username, email=email, password=password, role=User.Role.BUYER)
            log_action(ActivityVerb.USER_REGISTERED, actor=user, target=user)
    except IntegrityError as exc:
        if User.objects.filter(username=username).exists():
            raise UsernameTaken from exc
        raise
    return user


def flush_expired_tokens() -> int:
    deleted, _ = OutstandingToken.objects.filter(expires_at__lte=timezone.now()).delete()
    return deleted
