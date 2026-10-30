from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

from ticketing.mockdata import MOCK_USERNAME_PREFIX
from ticketing.mockdata import purge_mockdata


class Command(BaseCommand):
    help = (
        f'Delete mock events with their holds, orders, payments, and tickets, then the mock users ({MOCK_USERNAME_PREFIX}* with no email). '
        'Run it after the workers have drained, or tasks still queued for deleted orders end in dead letters.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Report what would be deleted, then roll back.')
        parser.add_argument('--yes', action='store_true', help='Skip the confirmation prompt.')

    def handle(self, *args, dry_run: bool, yes: bool, **options):
        if not dry_run and not yes and input('Delete all mock data? Type "purge" to continue: ').strip() != 'purge':
            raise CommandError('Aborted.')

        deleted = purge_mockdata(dry_run=dry_run)
        verb = 'Would delete' if dry_run else 'Deleted'
        summary = ', '.join(f'{count} {name}' for name, count in deleted.items() if name != 'users_kept')
        self.stdout.write(self.style.SUCCESS(f'{verb}: {summary}.'))
        if deleted['users_kept']:
            self.stdout.write(self.style.WARNING(f'Kept {deleted["users_kept"]} mock users that still hold tickets for real events.'))
