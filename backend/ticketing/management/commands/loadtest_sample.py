import csv
import time

import redis
from django.conf import settings
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

from ticketing.loadtest import SAMPLE_FIELDS
from ticketing.loadtest import sample_saturation


class Command(BaseCommand):
    help = 'Print database connection and queue backlog readings as CSV while a load test runs. Read-only.'

    def add_arguments(self, parser):
        parser.add_argument('--interval', type=float, default=5.0, metavar='SECONDS')
        parser.add_argument('--count', type=int, default=120, help='Number of readings; the default covers 10 minutes at 5 s.')

    def handle(self, *args, interval: float, count: int, **options):
        if interval <= 0 or count < 1:
            raise CommandError('--interval must be positive and --count at least 1.')

        client = redis.Redis.from_url(settings.CELERY_BROKER_URL, socket_connect_timeout=2, socket_timeout=5)
        writer = csv.DictWriter(self.stdout, fieldnames=SAMPLE_FIELDS, lineterminator='\n')
        writer.writeheader()
        for reading in range(count):
            writer.writerow(sample_saturation(client))
            self.stdout.flush()
            if reading < count - 1:
                time.sleep(interval)
