from django.conf import settings

from ticketrush.celery import app


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
