from .base import *  # noqa: F403
from .base import INSTALLED_APPS
from .celery import *  # noqa: F403


THIRD_PARTY_APPS = [
    'rest_framework',
    'rest_framework_simplejwt.token_blacklist',
    'drf_spectacular',
    'drf_spectacular_sidecar',
    'django_guid',
]

# Ordered by dependency direction: a later app may import from an earlier one, never the reverse.
LOCAL_APPS = [
    'accounts',
    'audit',
    'rest_framework_tracking',
    'reliability',
    'ticketing',
    'mockgateway',
    'payments',
    'notify',
]

INSTALLED_APPS += [
    *THIRD_PARTY_APPS,
    *LOCAL_APPS,
]
