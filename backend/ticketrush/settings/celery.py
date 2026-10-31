import tempfile
from pathlib import Path

from .base import REDIS_URL
from .base import TIME_ZONE
from .base import configs


CELERY_BROKER_URL = REDIS_URL or 'redis://localhost:6379/0'
# Results are not stored: every job outcome is recorded in PostgreSQL.
CELERY_RESULT_BACKEND = None
CELERY_TASK_IGNORE_RESULT = True

CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE

CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1

CELERY_TASK_SOFT_TIME_LIMIT = 60
CELERY_TASK_TIME_LIMIT = 90

CELERY_TASK_DEFAULT_QUEUE = 'critical'
CELERY_TASK_DEFAULT_EXCHANGE = 'critical'
CELERY_TASK_DEFAULT_ROUTING_KEY = 'critical'

# Webhook delivery confirms payments, so it stays off `bulk`, where rate-limited emails can hold every prefetch slot.
CELERY_TASK_ROUTES = {
    'mockgateway.*': {'queue': 'gateway'},
    'notify.*': {'queue': 'bulk'},
}

CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_BROKER_TRANSPORT_OPTIONS = {
    # Must exceed the hard time limit and every retry countdown, or Redis redelivers tasks still in flight.
    'visibility_timeout': 300,
    'socket_connect_timeout': 2,
    'socket_timeout': 5,
}

CELERY_TASK_ALWAYS_EAGER = configs.bool('CELERY_TASK_ALWAYS_EAGER', default=False)
CELERY_TASK_EAGER_PROPAGATES = True

# The image runs as a user that cannot write to /app, and beat exits when it cannot create this file.
CELERY_BEAT_SCHEDULE_FILENAME = str(Path(tempfile.gettempdir()) / 'celerybeat-schedule')

CELERY_BEAT_SCHEDULE: dict[str, dict] = {
    'relay-outbox': {'task': 'outbox.relay', 'schedule': 2.0, 'options': {'queue': 'critical', 'expires': 2}},
    'expire-holds': {'task': 'holds.expire_sweeper', 'schedule': 30.0, 'options': {'queue': 'critical', 'expires': 30}},
    'reconcile-payments': {'task': 'payments.reconcile', 'schedule': 30.0, 'options': {'queue': 'critical', 'expires': 30}},
    'flush-expired-tokens': {'task': 'accounts.flush_expired_tokens', 'schedule': 86400.0, 'options': {'queue': 'bulk', 'expires': 3600}},
}
