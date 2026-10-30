from django.db.models import TextChoices
from django.utils.translation import gettext_lazy as _


class ActivityVerb(TextChoices):
    USER_REGISTERED = 'user.registered', _('User registered')
    HOLD_CREATED = 'hold.created', _('Hold created')
    HOLD_RELEASED = 'hold.released', _('Hold released')
    HOLD_EXPIRED = 'hold.expired', _('Hold expired')
    ORDER_CREATED = 'order.created', _('Order created')
    ORDER_PAID = 'order.paid', _('Order paid')
    ORDER_PAYMENT_FAILED = 'order.payment_failed', _('Order payment failed')
    ORDER_PAID_UNFULFILLED = 'order.paid_unfulfilled', _('Order paid but unfulfilled')
    DEAD_LETTER_REPLAYED = 'dead_letter.replayed', _('Dead letter replayed')
    MOCKDATA_SEEDED = 'mockdata.seeded', _('Mock data seeded')
    MOCKDATA_PURGED = 'mockdata.purged', _('Mock data purged')
