from datetime import timedelta

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from tests.builders import make_user


BEFORE = [('ticketing', '0001_initial')]
AFTER = [('ticketing', '0002_event_details')]


@pytest.mark.django_db(transaction=True)
def test_events_that_were_on_sale_before_publishing_existed_stay_published():
    executor = MigrationExecutor(connection)
    executor.migrate(BEFORE)
    old_apps = executor.loader.project_state(BEFORE).apps
    organizer = make_user(username='organizer')
    now = timezone.now()
    old_apps.get_model('ticketing', 'Event').objects.create(
        organizer_id=organizer.pk,
        title='Already on sale',
        starts_at=now + timedelta(days=7),
        sale_opens_at=now,
        sale_closes_at=now + timedelta(days=1),
        capacity=10,
        available=10,
        price_satang=50_000,
    )

    executor = MigrationExecutor(connection)
    executor.migrate(AFTER)
    executor.loader.build_graph()
    new_apps = executor.loader.project_state(AFTER).apps
    event_model = new_apps.get_model('ticketing', 'Event')

    assert event_model.objects.get().is_published is True
    assert (
        event_model.objects.create(
            organizer_id=organizer.pk,
            title='New',
            starts_at=now,
            sale_opens_at=now,
            sale_closes_at=now + timedelta(days=1),
            capacity=1,
            available=1,
            price_satang=1,
        ).is_published
        is False
    )
