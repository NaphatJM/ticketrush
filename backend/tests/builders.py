from datetime import timedelta
from uuid import uuid4

from django.utils import timezone

from accounts.models import User
from ticketing.models import Event


def make_user(**overrides) -> User:
    fields = {'username': 'buyer', 'password': 'not-a-real-password'} | overrides
    password = fields.pop('password')
    return User.objects.create_user(password=password, **fields)


def make_event(**overrides) -> Event:
    now = timezone.now()
    fields = {
        'title': 'Launch night',
        'starts_at': now + timedelta(days=7),
        'sale_opens_at': now - timedelta(minutes=1),
        'sale_closes_at': now + timedelta(hours=1),
        'capacity': 10,
        'price_satang': 50_000,
        'max_per_user': 2,
    } | overrides
    if 'organizer' not in fields:
        fields['organizer'] = make_user(username=f'organizer-{uuid4().hex[:8]}', role=User.Role.ORGANIZER)
    fields.setdefault('available', fields['capacity'])
    return Event.objects.create(**fields)
