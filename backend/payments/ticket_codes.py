from uuid import UUID

from django.conf import settings
from django.core.signing import BadSignature
from django.core.signing import Signer


_SALT = 'ticketrush.ticket'


def _signer() -> Signer:
    return Signer(key=settings.TICKET_SIGNING_KEY, salt=_SALT, algorithm='sha256')


def sign_ticket(ticket_uuid: UUID) -> str:
    return _signer().sign(str(ticket_uuid))


def verify_ticket_code(code: str) -> UUID:
    """Return the ticket UUID a code was issued for; raises `BadSignature` for a forged or altered code."""
    try:
        return UUID(_signer().unsign(code))
    except ValueError as exc:
        raise BadSignature('malformed ticket code') from exc
