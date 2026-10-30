from datetime import timedelta

from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

from ticketing.loadtest import SCENARIOS
from ticketing.loadtest import seed_loadtest_event


class Command(BaseCommand):
    help = 'Create a published event for one load test run. Remove it afterwards with purge_mockdata.'

    def add_arguments(self, parser):
        parser.add_argument('--scenario', choices=sorted(SCENARIOS), required=True)
        parser.add_argument('--capacity', type=int, help='Defaults to the scenario capacity.')
        parser.add_argument('--max-per-user', type=int, help='Defaults to the scenario limit.')
        parser.add_argument('--opens-in', type=int, metavar='SECONDS', help='Seconds until the sale opens; defaults to the scenario delay.')

    def handle(self, *args, scenario: str, capacity: int | None, max_per_user: int | None, opens_in: int | None, **options):
        if capacity is not None and capacity < 1:
            raise CommandError('--capacity must be at least 1.')
        if max_per_user is not None and max_per_user < 1:
            raise CommandError('--max-per-user must be at least 1.')
        if opens_in is not None and opens_in < 0:
            raise CommandError('--opens-in must not be negative.')

        event = seed_loadtest_event(
            scenario=scenario,
            capacity=capacity,
            max_per_user=max_per_user,
            opens_in=None if opens_in is None else timedelta(seconds=opens_in),
        )
        self.stdout.write(self.style.SUCCESS(f'{event.title}: capacity {event.capacity}, max {event.max_per_user} per user.'))
        self.stdout.write(f'LOADTEST_EVENT={event.uuid}')
        self.stdout.write(f'Sale opens at {event.sale_opens_at.isoformat()}')
