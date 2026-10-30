from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
from urllib.parse import quote_plus

from django.contrib.auth.hashers import make_password
from django.db import transaction
from django.db.models import CharField
from django.db.models.functions import Cast
from django.utils import timezone

from accounts.models import User
from audit.constants import ActivityVerb
from audit.services import log_action
from mockgateway.models import MockCharge
from payments.models import Payment
from payments.models import Ticket
from payments.models import WebhookEvent

from .models import Event
from .models import Hold
from .models import Order


# Mock users are marked by this prefix plus an empty email; registration requires an email, so real buyers never match.
MOCK_USERNAME_PREFIX = 'mock-'
MOCK_ORGANIZER_USERNAME = f'{MOCK_USERNAME_PREFIX}organizer'
MOCK_BUYER_USERNAME = f'{MOCK_USERNAME_PREFIX}buyer-{{:05d}}'

SMALL_EVENT_MAX_CAPACITY = 300
MEDIUM_EVENT_MAX_CAPACITY = 2000

ON_SALE = Event.SaleStatus.ON_SALE
UPCOMING = Event.SaleStatus.UPCOMING
SOLD_OUT = Event.SaleStatus.SOLD_OUT
CLOSED = Event.SaleStatus.CLOSED

DEFAULT_IMPORTANT_INFO = (
    'Show the QR code from your ticket email or My tickets at the entrance. Each code is scanned once.\n'
    'Tickets are non-refundable and cannot be resold.'
)


def _banner(photo_id: str) -> str:
    return f'https://images.unsplash.com/photo-{photo_id}?w=1600&q=80&auto=format&fit=crop'


@dataclass(frozen=True)
class MockEvent:
    title: str
    category: str
    capacity: int
    price_baht: int
    sale: str
    starts_in_days: float
    summary: str
    description: str
    venue_name: str
    venue_address: str
    presented_by: str
    photo_id: str
    sold_ratio: float = 0.0
    opens_in_hours: float = 0.0
    duration_hours: float = 3
    max_per_user: int = 2
    published: bool = True
    important_info: str = DEFAULT_IMPORTANT_INFO

    @property
    def is_small(self) -> bool:
        return self.capacity <= SMALL_EVENT_MAX_CAPACITY

    def fields(self, now: datetime) -> dict:
        starts_at = now + timedelta(days=self.starts_in_days)
        if self.sale == UPCOMING:
            sale_opens_at = now + timedelta(hours=self.opens_in_hours)
            sale_closes_at = starts_at - timedelta(hours=1)
        elif self.sale == CLOSED:
            sale_closes_at = min(starts_at, now) - timedelta(hours=1)
            sale_opens_at = sale_closes_at - timedelta(days=30)
        else:
            sale_opens_at = now - timedelta(days=2)
            sale_closes_at = starts_at - timedelta(hours=1)
        sold = self.capacity if self.sale == SOLD_OUT else round(self.capacity * self.sold_ratio)
        return {
            'summary': self.summary,
            'description': self.description,
            'important_info': self.important_info,
            'category': self.category,
            'presented_by': self.presented_by,
            'banner_url': _banner(self.photo_id),
            'venue_name': self.venue_name,
            'venue_address': self.venue_address,
            'venue_map_url': f'https://www.google.com/maps/search/?api=1&query={quote_plus(f"{self.venue_name} {self.venue_address}")}',
            'is_published': self.published,
            'starts_at': starts_at,
            'ends_at': starts_at + timedelta(hours=self.duration_hours),
            'sale_opens_at': sale_opens_at,
            'sale_closes_at': sale_closes_at,
            'capacity': self.capacity,
            'available': self.capacity - sold,
            'price_satang': self.price_baht * 100,
            'max_per_user': self.max_per_user,
        }


C = Event.Category

MOCK_EVENTS: tuple[MockEvent, ...] = (
    # Small events.
    MockEvent(
        title='Flash Drop: 100 Seats',
        category=C.CONCERT,
        capacity=100,
        price_baht=590,
        sale=ON_SALE,
        starts_in_days=10,
        summary='One hundred seats, two per person, first come first served.',
        description='A surprise live set in a small hall. The seats are few on purpose: this is the event to race for.',
        venue_name='Lido Connect Hall 2',
        venue_address='Rama I Rd, Pathum Wan, Bangkok',
        presented_by='TicketRush Live',
        photo_id='1501281668745-f7f57925c3b4',
    ),
    MockEvent(
        title='Jazz Night at the Corner Room',
        category=C.CONCERT,
        capacity=120,
        price_baht=650,
        sale=ON_SALE,
        starts_in_days=3,
        sold_ratio=0.97,
        summary='A late-night quartet in an intimate room. Almost sold out.',
        description='Two sets of standards and originals from a Bangkok jazz quartet.\nFirst set at 20:00, second at 21:30.',
        venue_name='The Corner Room',
        venue_address='Sukhumvit Soi 11, Watthana, Bangkok',
        presented_by='Blue Hour Music',
        photo_id='1507676184212-d03ab07a01bf',
    ),
    MockEvent(
        title='Film Photography Walk: Old Town',
        category=C.WORKSHOP,
        capacity=24,
        price_baht=890,
        sale=ON_SALE,
        starts_in_days=4,
        sold_ratio=0.4,
        duration_hours=4,
        summary='Shoot a roll of film around Rattanakosin with a guide.',
        description='A guided photo walk through the old town. One roll of 35 mm film and development are included.\nBring your own camera.',
        venue_name='Museum Siam',
        venue_address='Sanam Chai Rd, Phra Nakhon, Bangkok',
        presented_by='Grain Club',
        photo_id='1452587925148-ce544e77e70d',
    ),
    MockEvent(
        title='Open Mic Comedy: New Voices',
        category=C.COMEDY,
        capacity=90,
        price_baht=300,
        sale=UPCOMING,
        starts_in_days=5,
        opens_in_hours=0.25,
        summary='Ten new comics, five minutes each. Sale opens in minutes.',
        description='The monthly showcase for first-time comics. Expect surprises.',
        venue_name='Comedy Lab Silom',
        venue_address='Silom Soi 4, Bang Rak, Bangkok',
        presented_by='Punchline Club',
        photo_id='1475721027785-f74eccf877e2',
    ),
    MockEvent(
        title='Django at Scale Meetup',
        category=C.CONFERENCE,
        capacity=200,
        price_baht=0,
        sale=UPCOMING,
        starts_in_days=14,
        opens_in_hours=24,
        summary='Talks on queues, idempotency, and Postgres locks.',
        description='Three talks from teams running Django in production, then pizza.',
        venue_name='True Digital Park',
        venue_address='Sukhumvit Rd, Phra Khanong, Bangkok',
        presented_by='Python Bangkok',
        photo_id='1522202176988-66273c2fd55f',
    ),
    MockEvent(
        title="Chef's Table: Northern Thai",
        category=C.OTHER,
        capacity=30,
        price_baht=3500,
        sale=SOLD_OUT,
        starts_in_days=7,
        duration_hours=2.5,
        summary='A nine-course tasting menu from Chiang Mai.',
        description='A guest chef cooks a nine-course northern Thai menu at one long table.',
        venue_name='Long Table Ekkamai',
        venue_address='Ekkamai Soi 10, Watthana, Bangkok',
        presented_by='Table for Thirty',
        photo_id='1556125574-d7f27ec36a06',
    ),
    MockEvent(
        title='Stand-up Late Show',
        category=C.COMEDY,
        capacity=180,
        price_baht=550,
        sale=CLOSED,
        starts_in_days=-3,
        sold_ratio=0.82,
        duration_hours=2,
        summary='The late show has ended. See you at the next one.',
        description='Headliners from the Bangkok circuit in a late-night set.',
        venue_name='Comedy Lab Silom',
        venue_address='Silom Soi 4, Bang Rak, Bangkok',
        presented_by='Punchline Club',
        photo_id='1475721027785-f74eccf877e2',
    ),
    MockEvent(
        title='Pottery for Beginners',
        category=C.WORKSHOP,
        capacity=16,
        price_baht=1500,
        sale=ON_SALE,
        starts_in_days=20,
        published=False,
        duration_hours=3,
        summary='Draft: wheel-throwing basics.',
        description='Learn to centre and throw on the wheel. Pieces are fired and ready two weeks later.',
        venue_name='Clay Studio Bangkok',
        venue_address='Charoen Krung Soi 30, Bang Rak, Bangkok',
        presented_by='Clay Studio Bangkok',
        photo_id='1452587925148-ce544e77e70d',
    ),
    # Medium events.
    MockEvent(
        title='Thailand Developer Summit',
        category=C.CONFERENCE,
        capacity=1500,
        price_baht=1200,
        sale=ON_SALE,
        starts_in_days=40,
        sold_ratio=0.96,
        duration_hours=9,
        max_per_user=4,
        summary='Two days of talks on web, cloud, and AI. Last few seats.',
        description='Keynotes, four tracks of talks, and a hiring fair.',
        venue_name='Queen Sirikit National Convention Center',
        venue_address='Ratchadaphisek Rd, Khlong Toei, Bangkok',
        presented_by='DevThai',
        photo_id='1540575467063-178a50c2df87',
    ),
    MockEvent(
        title='City Night Run 10K',
        category=C.SPORTS,
        capacity=1200,
        price_baht=900,
        sale=ON_SALE,
        starts_in_days=22,
        sold_ratio=0.35,
        max_per_user=4,
        summary='A 10K through the old town after dark.',
        description='A night run past the temples and the river. Finisher medal and shirt included.',
        venue_name='Sanam Luang',
        venue_address='Na Phra That Rd, Phra Nakhon, Bangkok',
        presented_by='Run the City',
        photo_id='1461896836934-ffe607ba8211',
        important_info='Collect your race bib with your QR code the day before.\n' + DEFAULT_IMPORTANT_INFO,
    ),
    MockEvent(
        title='Siam Lights: The Musical',
        category=C.THEATRE,
        capacity=800,
        price_baht=2200,
        sale=UPCOMING,
        starts_in_days=45,
        opens_in_hours=120,
        duration_hours=2.5,
        max_per_user=4,
        summary='A new musical about a Bangkok family across three generations.',
        description='A new Thai musical with a live orchestra.',
        venue_name='Muangthai Rachadalai Theatre',
        venue_address='Ratchadaphisek Rd, Huai Khwang, Bangkok',
        presented_by='Siam Stage Company',
        photo_id='1585699324551-f6c309eedeca',
    ),
    MockEvent(
        title='Indie Showcase Vol. 7',
        category=C.CONCERT,
        capacity=600,
        price_baht=490,
        sale=SOLD_OUT,
        starts_in_days=2,
        max_per_user=4,
        summary='Four indie bands on one stage.',
        description='The seventh showcase of new Bangkok indie bands.',
        venue_name='Union Hall',
        venue_address='Union Mall, Lat Phrao, Bangkok',
        presented_by='Garage Tapes',
        photo_id='1574391884720-bbc3740c59d1',
    ),
    MockEvent(
        title='Startup Expo Bangkok',
        category=C.CONFERENCE,
        capacity=1000,
        price_baht=500,
        sale=CLOSED,
        starts_in_days=-10,
        sold_ratio=0.76,
        duration_hours=8,
        max_per_user=4,
        summary='The expo has ended. Thanks to everyone who came.',
        description='Eighty startups, one hall, and a pitch stage.',
        venue_name='BITEC Bangna',
        venue_address='Bang Na-Trat Rd, Bang Na, Bangkok',
        presented_by='Campus Ventures',
        photo_id='1531058020387-3be344556be6',
    ),
    MockEvent(
        title='New Year Gala Dinner',
        category=C.OTHER,
        capacity=500,
        price_baht=6500,
        sale=UPCOMING,
        starts_in_days=62,
        opens_in_hours=240,
        published=False,
        duration_hours=4,
        max_per_user=6,
        summary='Draft: a ballroom dinner with a live band.',
        description='A five-course dinner in the grand ballroom, then a countdown on the terrace.',
        venue_name='Grand Ballroom Riverside',
        venue_address='Charoen Krung Rd, Bang Rak, Bangkok',
        presented_by='Table for Thirty',
        photo_id='1519167758481-83f550bb49b3',
    ),
)


@dataclass(frozen=True)
class SeedResult:
    events_created: int
    events_existing: int
    buyers_created: int
    buyers_existing: int


@transaction.atomic
def seed_mockdata(*, buyers: int = 0, buyer_password: str | None = None, now: datetime | None = None) -> SeedResult:
    """Create the mock events and buyers that are missing; existing rows are left untouched."""
    if buyers and not buyer_password:
        raise ValueError('buyer_password is required when creating buyers')
    now = now or timezone.now()
    organizer, _ = User.objects.get_or_create(
        username=MOCK_ORGANIZER_USERNAME,
        defaults={'email': '', 'role': User.Role.ORGANIZER, 'password': make_password(None)},
    )
    events_created = 0
    for spec in MOCK_EVENTS:
        _, created = Event.objects.get_or_create(organizer=organizer, title=spec.title, defaults=spec.fields(now))
        events_created += created

    usernames = [MOCK_BUYER_USERNAME.format(n) for n in range(1, buyers + 1)]
    existing = set(User.objects.filter(username__in=usernames).values_list('username', flat=True))
    # One hash for every buyer: hashing per user would take minutes for a load-test population.
    password = make_password(buyer_password) if buyers else ''
    User.objects.bulk_create(
        [User(username=name, email='', role=User.Role.BUYER, password=password) for name in usernames if name not in existing],
        batch_size=1000,
    )

    result = SeedResult(
        events_created=events_created,
        events_existing=len(MOCK_EVENTS) - events_created,
        buyers_created=len(usernames) - len(existing),
        buyers_existing=len(existing),
    )
    log_action(ActivityVerb.MOCKDATA_SEEDED, detail=result.__dict__)
    return result


def mock_users():
    return User.objects.filter(username__startswith=MOCK_USERNAME_PREFIX, email='')


@transaction.atomic
def purge_mockdata(*, dry_run: bool = False) -> dict[str, int]:
    """Delete mock events with everything bought on them, then the mock users left without holds or events.

    Holds that mock buyers placed on real events are kept, because deleting them would lose that event's stock.
    """
    events = Event.objects.filter(organizer__in=mock_users())
    orders = Order.objects.filter(hold__event__in=events)
    payment_keys = Payment.objects.filter(order__in=orders).annotate(key=Cast('uuid', output_field=CharField())).values('key')

    deleted = {
        'tickets': Ticket.objects.filter(order__in=orders).delete()[0],
        'webhook_events': WebhookEvent.objects.filter(payment_key__in=payment_keys).delete()[0],
        'mock_charges': MockCharge.objects.filter(idempotency_key__in=payment_keys).delete()[0],
        'payments': Payment.objects.filter(order__in=orders).delete()[0],
        'orders': orders.delete()[0],
        'holds': Hold.objects.filter(event__in=events).delete()[0],
        'events': events.delete()[0],
    }
    removable = list(mock_users().filter(holds__isnull=True, events__isnull=True).values_list('pk', flat=True))
    User.objects.filter(pk__in=removable).delete()
    deleted['users'] = len(removable)
    deleted['users_kept'] = mock_users().count()

    log_action(ActivityVerb.MOCKDATA_PURGED, detail=deleted | {'dry_run': dry_run})
    if dry_run:
        transaction.set_rollback(True)
    return deleted
