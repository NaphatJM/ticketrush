import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from django_guid.integrations import CeleryIntegration

from utils.configs_loader import load_configs


PROJECT_PATH = Path(__file__).resolve().parent.parent
BASE = PROJECT_PATH.parent

configs = load_configs(BASE)

# Read from the module name because test.py overrides DEBUG only after this file has run.
_IS_TEST = os.environ.get('DJANGO_SETTINGS_MODULE', '').endswith('.test')

DEBUG = configs.bool('DEBUG', default=False)


def _required_in_prod(name: str, value, why: str):
    if not value and not DEBUG and not _IS_TEST:
        raise ImproperlyConfigured(f'DJANGO_{name} is required when DEBUG is False: {why}')
    return value


SECRET_KEY = (
    _required_in_prod(
        'SECRET_KEY',
        configs.str('SECRET_KEY', default=''),
        'it signs sessions, password-reset tokens, and JWTs',
    )
    or 'dev-only-insecure-key'
)

ALLOWED_HOSTS = _required_in_prod(
    'ALLOWED_HOSTS',
    configs.list('ALLOWED_HOSTS', default=[]),
    'an open Host header allows cache poisoning and password-reset link spoofing',
) or ['localhost', '127.0.0.1']

CSRF_TRUSTED_ORIGINS = configs.list('CSRF_TRUSTED_ORIGINS', default=[])

READINESS_TOKEN = configs.str('READINESS_TOKEN', default='')

TRUST_FORWARDED_FOR = configs.bool('TRUST_FORWARDED_FOR', default=False)

_LOG_LEVELS = frozenset({'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'})
LOG_LEVEL = (configs.str('LOG_LEVEL', default='INFO') or 'INFO').strip().upper()
if LOG_LEVEL not in _LOG_LEVELS:
    LOG_LEVEL = 'INFO'

SERVICE_NAME = os.environ.get('OTEL_SERVICE_NAME', 'ticketrush')
ENVIRONMENT = configs.str('ENVIRONMENT', default='development')

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'whitenoise.runserver_nostatic',
    'django.contrib.staticfiles',
]

MIDDLEWARE = [
    # First, so every later middleware and log line already has the correlation id.
    'django_guid.middleware.guid_middleware',
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'audit.middleware.client_ip_middleware',
]

ROOT_URLCONF = 'ticketrush.urls'
WSGI_APPLICATION = 'ticketrush.wsgi.application'

AUTH_USER_MODEL = 'accounts.User'

# ==== Database ====

DATABASE_URL = _required_in_prod(
    'DATABASE_URL',
    configs.str('DATABASE_URL', default=''),
    'the oversell guarantees depend on PostgreSQL row locking and constraints',
)
DATABASES = {'default': configs.db_url_config(DATABASE_URL) if DATABASE_URL else {}}
DATABASES['default'].setdefault('OPTIONS', {}).setdefault('connect_timeout', 5)
DATABASES['default']['CONN_MAX_AGE'] = configs.int('DB_CONN_MAX_AGE', default=60)
DATABASES['default']['CONN_HEALTH_CHECKS'] = True

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ==== Redis ====

REDIS_URL = configs.str('REDIS_URL', default='')
if REDIS_URL:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.redis.RedisCache',
            'LOCATION': REDIS_URL,
            'OPTIONS': {'socket_connect_timeout': 5, 'socket_timeout': 5},
        },
    }
elif DEBUG or _IS_TEST:
    CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
else:
    raise ImproperlyConfigured('DJANGO_REDIS_URL is required when DEBUG is False: it is the Celery broker and the shared throttle store')

# ==== i18n / static ====

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Bangkok'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = str(BASE / 'static_root')
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'},
}

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# ==== HTTPS ====

USE_HTTPS = configs.bool('USE_HTTPS', default=False)
SECURE_SSL_REDIRECT = USE_HTTPS
SESSION_COOKIE_SECURE = USE_HTTPS
CSRF_COOKIE_SECURE = USE_HTTPS
# Platform health checks reach the container over plain HTTP.
SECURE_REDIRECT_EXEMPT = [r'^system/']
if USE_HTTPS:
    # Railway's edge terminates TLS and overwrites X-Forwarded-Proto.
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'same-origin'
X_FRAME_OPTIONS = 'DENY'

# ==== DRF ====

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': ('rest_framework.authentication.SessionAuthentication',),
    'DEFAULT_PERMISSION_CLASSES': ('rest_framework.permissions.IsAuthenticated',),
    'DEFAULT_RENDERER_CLASSES': ('rest_framework.renderers.JSONRenderer',),
    'DEFAULT_PAGINATION_CLASS': 'utils.drf_helper.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
    'EXCEPTION_HANDLER': 'utils.drf_helper.rest_exception_handler.exception_handler',
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
}

SPECTACULAR_SETTINGS = {
    'TITLE': 'TicketRush API',
    'DESCRIPTION': 'Flash-sale ticketing API.',
    'VERSION': '0.1.0',
    'SERVE_INCLUDE_SCHEMA': False,
    'SWAGGER_UI_DIST': 'SIDECAR',
    'SWAGGER_UI_FAVICON_HREF': 'SIDECAR',
    'REDOC_DIST': 'SIDECAR',
}

# ==== Request tracking ====

#: Successful reads are not stored; slower requests are stored regardless of status.
DRF_TRACKING_SLOW_MS = configs.int('DRF_TRACKING_SLOW_MS', default=2500)

# ==== Correlation id ====

DJANGO_GUID = {
    'GUID_HEADER_NAME': 'Correlation-ID',
    'VALIDATE_GUID': True,
    'RETURN_HEADER': True,
    'EXPOSE_HEADER': True,
    'INTEGRATIONS': [CeleryIntegration(use_django_logging=True, log_parent=True)],
}

LOGGING = {
    'version': 1,
    'disable_existing_loggers': True,
    'filters': {
        'correlation_id': {'()': 'django_guid.log_filters.CorrelationId'},
        'celery_tracing': {'()': 'django_guid.integrations.celery.log_filters.CeleryTracing'},
    },
    'formatters': {
        'json': {
            '()': 'utils.log_formatters.JsonFormatter',
            'service': SERVICE_NAME,
            'environment': ENVIRONMENT,
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'json',
            'filters': ['correlation_id', 'celery_tracing'],
        },
    },
    'loggers': {
        'django': {'handlers': ['console'], 'level': 'WARNING', 'propagate': False},
        'django.request': {'handlers': ['console'], 'level': 'WARNING', 'propagate': False},
        'celery': {'handlers': ['console'], 'level': 'INFO', 'propagate': False},
        'accounts': {'handlers': ['console'], 'level': LOG_LEVEL, 'propagate': False},
        'audit': {'handlers': ['console'], 'level': LOG_LEVEL, 'propagate': False},
        'rest_framework_tracking': {'handlers': ['console'], 'level': LOG_LEVEL, 'propagate': False},
        'utils': {'handlers': ['console'], 'level': LOG_LEVEL, 'propagate': False},
        'ticketrush': {'handlers': ['console'], 'level': LOG_LEVEL, 'propagate': False},
    },
    # Loggers outside the list above would otherwise fall back to logging.lastResort: no cid, no JSON.
    'root': {'handlers': ['console'], 'level': 'WARNING'},
}
