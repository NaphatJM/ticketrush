import logging
from collections.abc import Callable

import redis
from django.conf import settings
from django.db import connection
from django.http import HttpRequest
from django.http import JsonResponse
from django.utils.crypto import constant_time_compare
from django.views.decorators.http import require_safe


logger = logging.getLogger(__name__)


def check_postgres() -> None:
    with connection.cursor() as cursor:
        cursor.execute('SELECT 1')


def check_redis() -> None:
    client = redis.Redis.from_url(settings.REDIS_URL, socket_connect_timeout=1, socket_timeout=1)
    try:
        client.ping()
    finally:
        client.close()


def _run_checks(checks: dict[str, Callable[[], None]]) -> dict[str, str]:
    results = {}
    for name, check in checks.items():
        try:
            check()
        except Exception:
            logger.exception('dependency check failed', extra={'check': name})
            results[name] = 'fail'
        else:
            results[name] = 'ok'
    return results


@require_safe
def healthcheck(request: HttpRequest) -> JsonResponse:
    """Liveness: the process answers. Touches no dependency, so an outage cannot trigger restart loops."""
    return JsonResponse({'status': 'healthy'})


@require_safe
def readiness(request: HttpRequest) -> JsonResponse:
    """Deploy gate: PostgreSQL only, so a Redis outage cannot block a deploy or a rollback."""
    results = _run_checks({'postgres': check_postgres})
    ready = results['postgres'] == 'ok'
    return JsonResponse({'status': 'ready' if ready else 'unavailable'}, status=200 if ready else 503)


def _may_see_dependencies(request: HttpRequest) -> bool:
    if settings.READINESS_TOKEN:
        return constant_time_compare(request.headers.get('X-Readiness-Token', ''), settings.READINESS_TOKEN)
    return bool(getattr(request.user, 'is_staff', False))


@require_safe
def dependencies(request: HttpRequest) -> JsonResponse:
    """Per-dependency status for alerts and synthetic checks; gated because it reveals topology."""
    if not _may_see_dependencies(request):
        return JsonResponse({'status': 'forbidden'}, status=403)
    results = _run_checks({'postgres': check_postgres, 'redis': check_redis})
    healthy = all(result == 'ok' for result in results.values())
    return JsonResponse(
        {'status': 'ok' if healthy else 'unavailable', 'checks': results},
        status=200 if healthy else 503,
    )
