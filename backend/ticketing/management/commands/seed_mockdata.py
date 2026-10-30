from getpass import getpass

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

from ticketing.mockdata import MOCK_BUYER_USERNAME
from ticketing.mockdata import seed_mockdata


class Command(BaseCommand):
    help = 'Create the mock events (and optional load-test buyers) that are missing. Safe to run repeatedly.'

    def add_arguments(self, parser):
        parser.add_argument('--buyers', type=int, default=0, help=f'Number of buyers to ensure, named {MOCK_BUYER_USERNAME.format(1)} and up.')
        parser.add_argument('--buyer-password', help='Password for new buyers; prompted for when omitted.')

    def handle(self, *args, buyers: int, buyer_password: str | None, **options):
        if buyers < 0:
            raise CommandError('--buyers must not be negative.')
        if buyers and not buyer_password:
            buyer_password = getpass('Password for new mock buyers: ')
        if buyers:
            try:
                validate_password(buyer_password)
            except ValidationError as exc:
                raise CommandError(' '.join(exc.messages)) from exc

        result = seed_mockdata(buyers=buyers, buyer_password=buyer_password)
        self.stdout.write(self.style.SUCCESS(f'Events: {result.events_created} created, {result.events_existing} already present.'))
        if buyers:
            self.stdout.write(self.style.SUCCESS(f'Buyers: {result.buyers_created} created, {result.buyers_existing} already present.'))
