import json
from argparse import ArgumentTypeError
from datetime import datetime

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

from ticketing.loadtest import verify_event
from ticketing.models import Event


def _aware_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ArgumentTypeError('include a UTC offset, for example 2026-10-30T14:00:00+00:00')
    return parsed


class Command(BaseCommand):
    help = 'Check the stock and ticket invariants of a load test event. Read-only; exits 1 when a check fails.'

    def add_arguments(self, parser):
        parser.add_argument('--event', required=True, help='Event UUID.')
        parser.add_argument('--since', type=_aware_datetime, help='Count dead letters from this ISO time only; include the UTC offset.')

    def handle(self, *args, event: str, since: datetime | None, **options):
        try:
            target = Event.objects.get(uuid=event)
        except (Event.DoesNotExist, ValidationError) as exc:
            raise CommandError(f'No event with UUID {event}.') from exc

        report = verify_event(target, since=since)
        self.stdout.write(json.dumps(report, indent=2))
        if not report['ok']:
            failed = ', '.join(name for name, ok in report['checks'].items() if not ok)
            raise CommandError(f'Checks failed: {failed}', returncode=1)
