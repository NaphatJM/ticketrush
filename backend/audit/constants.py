from django.db.models import TextChoices
from django.utils.translation import gettext_lazy as _


class ActivityVerb(TextChoices):
    USER_REGISTERED = 'user.registered', _('User registered')
    HOLD_CREATED = 'hold.created', _('Hold created')
    HOLD_RELEASED = 'hold.released', _('Hold released')
    HOLD_EXPIRED = 'hold.expired', _('Hold expired')
