from .settings import *  # noqa: F403


DEBUG = True

# Tests run on PostgreSQL from DJANGO_DATABASE_URL: the concurrency tests need real row locks.

PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']

STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# A named location gives the suite its own store, separate from any other LocMemCache.
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'ticketrush-tests',
    },
}

WHITENOISE_AUTOREFRESH = True
