import os
import subprocess
import sys
from pathlib import Path

from django.conf import settings

from reliability.tasks import RETRY_BACKOFF_MAX_SECONDS
from ticketrush.celery import app


BACKEND = Path(__file__).resolve().parent.parent


def test_tasks_are_acknowledged_late_and_requeued_when_a_worker_dies():
    assert app.conf.task_acks_late is True
    assert app.conf.task_reject_on_worker_lost is True
    assert app.conf.worker_prefetch_multiplier == 1


def test_soft_time_limit_leaves_room_before_the_hard_limit():
    assert app.conf.task_soft_time_limit < app.conf.task_time_limit


def test_visibility_timeout_exceeds_the_hard_time_limit():
    assert settings.CELERY_BROKER_TRANSPORT_OPTIONS['visibility_timeout'] > app.conf.task_time_limit


def test_every_scheduled_task_is_registered():
    app.loader.import_default_modules()

    for name, entry in settings.CELERY_BEAT_SCHEDULE.items():
        assert entry['task'] in app.tasks, f'beat entry {name!r} points at an unregistered task'


def test_retry_backoff_stays_below_the_visibility_timeout():
    assert RETRY_BACKOFF_MAX_SECONDS < settings.CELERY_BROKER_TRANSPORT_OPTIONS['visibility_timeout']


def test_webhook_delivery_runs_on_gateway_email_on_bulk_and_payment_processing_on_critical():
    router = app.amqp.router

    assert router.route({}, 'mockgateway.deliver_webhook')['queue'].name == 'gateway'
    assert router.route({}, 'payments.process_succeeded')['queue'].name == 'critical'
    assert router.route({}, 'notify.send_ticket_email')['queue'].name == 'bulk'


def test_payments_are_reconciled_on_critical_at_least_every_minute():
    entry = settings.CELERY_BEAT_SCHEDULE['reconcile-payments']

    assert entry['task'] == 'payments.reconcile'
    assert entry['options']['queue'] == 'critical'
    assert 30 <= entry['schedule'] <= 60


def test_a_fresh_web_process_can_publish_every_outbox_topic():
    script = (
        'import django; django.setup(); '
        'from reliability.outbox import task_by_name; '
        "[task_by_name(name) for name in ('payments.process_succeeded', 'payments.process_failed', 'notify.send_ticket_email')]"
    )
    env = os.environ | {'DJANGO_SETTINGS_MODULE': 'ticketrush.settings.test'}

    result = subprocess.run([sys.executable, '-c', script], cwd=BACKEND, env=env, capture_output=True, text=True, check=False)  # noqa: S603

    assert result.returncode == 0, result.stderr
