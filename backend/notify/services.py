import base64
import io
import logging

import segno
from django.conf import settings
from django.template.loader import render_to_string

from payments.models import Ticket
from ticketing.models import Order

from . import resend


logger = logging.getLogger(__name__)


def send_ticket_email(*, order_id: int) -> str:
    order = Order.objects.select_related('hold__event', 'hold__user').get(pk=order_id)
    tickets = list(Ticket.objects.filter(order=order).order_by('seq'))
    if not tickets:
        raise ValueError(f'order {order.uuid} has no tickets to email')
    address = order.hold.user.email
    if not address:
        logger.warning('ticket email skipped: buyer has no email address', extra={'order_id': str(order.uuid)})
        return 'no_address'
    if not settings.RESEND_API_KEY:
        logger.warning('ticket email skipped: DJANGO_RESEND_API_KEY is empty', extra={'order_id': str(order.uuid)})
        return 'disabled'

    email_id = resend.send_email(
        api_key=settings.RESEND_API_KEY,
        message=build_ticket_email(order, tickets, to=address),
        idempotency_key=f'ticket-email/{order.uuid}',
    )
    logger.info('ticket email sent', extra={'order_id': str(order.uuid), 'tickets': len(tickets), 'email_id': email_id})
    return 'sent'


def build_ticket_email(order: Order, tickets: list[Ticket], *, to: str) -> dict:
    """Render the message. It must be the same for every retry: Resend rejects a reused idempotency key with a different body."""
    event = order.hold.event
    context = {
        'event': event,
        'order': order,
        'amount': f'{order.amount_satang / 100:,.2f}',
        'tickets': [{'seq': ticket.seq, 'code': ticket.code, 'cid': f'ticket-{ticket.seq}'} for ticket in tickets],
    }
    return {
        'from': settings.EMAIL_FROM,
        'to': [to],
        'subject': f'Your tickets for {event.title}',
        'html': render_to_string('notify/ticket_email.html', context),
        'text': render_to_string('notify/ticket_email.txt', context),
        'attachments': [
            {
                'filename': f'ticket-{ticket.seq}.png',
                'content': _qr_png(ticket.code),
                'content_type': 'image/png',
                'content_id': f'ticket-{ticket.seq}',
            }
            for ticket in tickets
        ],
    }


def _qr_png(code: str) -> str:
    buffer = io.BytesIO()
    segno.make(code, error='m').save(buffer, kind='png', scale=8, border=4)
    return base64.b64encode(buffer.getvalue()).decode()
