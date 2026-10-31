import os

from celery import Celery
from celery.signals import beat_init
from celery.signals import worker_process_init
from celery.signals import worker_process_shutdown

from . import telemetry


os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ticketrush.settings.settings')

app = Celery('ticketrush')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()


@worker_process_init.connect
def start_worker_telemetry(**kwargs) -> None:
    telemetry.configure()


@worker_process_shutdown.connect
def flush_worker_telemetry(**kwargs) -> None:
    telemetry.shutdown()


@beat_init.connect
def start_beat_telemetry(**kwargs) -> None:
    if telemetry.configure():
        from . import system_metrics  # noqa: PLC0415 -- it imports models, which need the app registry

        # Beat runs as exactly one replica, so these system-wide gauges are reported once.
        system_metrics.register()
