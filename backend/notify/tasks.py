from celery import shared_task

from reliability.tasks import DeadLetterTask

from . import services
from .resend import EmailRejectedError


# Per worker; Resend allows 10 requests per second across the team, and a sale pays many orders at once.
@shared_task(name='notify.send_ticket_email', base=DeadLetterTask, max_retries=8, dont_autoretry_for=(EmailRejectedError,), rate_limit='5/s')
def send_ticket_email(*, order_id: int) -> str:
    return services.send_ticket_email(order_id=order_id)
