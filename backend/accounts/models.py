from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _

from db.utils import uuid7


class User(AbstractUser):
    class Role(models.TextChoices):
        BUYER = 'buyer'
        ORGANIZER = 'organizer'

    uuid = models.UUIDField(_('UUID'), default=uuid7, unique=True, editable=False)
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.BUYER)

    class Meta(AbstractUser.Meta):
        constraints = [
            # Mock users have no email, so only non-empty addresses must be unique.
            models.UniqueConstraint(Lower('email'), condition=~Q(email=''), name='accounts_user_email_ci_unique'),
        ]
