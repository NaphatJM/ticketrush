import pytest
from django.db import transaction
from django_guid import set_guid

from audit.constants import ActivityVerb
from audit.models import ActivityLog
from audit.services import log_action
from tests.builders import make_user


pytestmark = pytest.mark.django_db


def test_a_row_records_actor_target_and_correlation_id():
    user = make_user()
    set_guid('cid-123')

    row = log_action(ActivityVerb.USER_REGISTERED, actor=user, target=user, detail={'role': 'buyer'})

    assert row.verb == 'user.registered'
    assert row.actor == user
    assert row.actor_username == 'buyer'
    assert row.target_label == 'accounts.User'
    assert row.target_id == str(user.uuid)
    assert row.cid == 'cid-123'
    assert row.detail == {'role': 'buyer'}


def test_the_username_survives_a_later_rename():
    user = make_user()
    log_action(ActivityVerb.USER_REGISTERED, actor=user)

    user.username = 'renamed'
    user.save()

    assert ActivityLog.objects.get().actor_username == 'buyer'


def test_the_row_rolls_back_with_the_change_it_describes():
    with pytest.raises(RuntimeError), transaction.atomic():
        user = make_user()
        log_action(ActivityVerb.USER_REGISTERED, actor=user)
        raise RuntimeError('domain step failed')

    assert not ActivityLog.objects.exists()
