import os
import subprocess
import sys
from pathlib import Path


BACKEND = Path(__file__).resolve().parent.parent

PRODUCTION_ENV = {
    'DJANGO_SETTINGS_MODULE': 'ticketrush.settings.settings',
    'DJANGO_READ_DOT_ENV_FILE': 'False',
    'DJANGO_DEBUG': 'False',
    'DJANGO_SECRET_KEY': 'x' * 50,
    'DJANGO_ALLOWED_HOSTS': 'api.example.test',
    'DJANGO_DATABASE_URL': 'postgres://user:pass@db.example.test:5432/ticketrush',
    'DJANGO_REDIS_URL': 'redis://redis.example.test:6379/0',
    'DJANGO_PUBLIC_API_URL': 'https://api.example.test',
    'DJANGO_MOCK_GATEWAY_WEBHOOK_SECRET': 'w' * 32,
    'DJANGO_TICKET_SIGNING_KEY': 't' * 50,
    'DJANGO_RESEND_API_KEY': 're_placeholder',
}


def _load_settings(env: dict[str, str]) -> subprocess.CompletedProcess:
    base = {key: value for key, value in os.environ.items() if not key.startswith('DJANGO_')}
    return subprocess.run(  # noqa: S603
        [sys.executable, '-c', 'import django; django.setup(); from django.conf import settings; print(settings.DATABASES["default"]["HOST"])'],
        cwd=BACKEND,
        env=base | env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_production_settings_boot_with_every_required_value():
    result = _load_settings(PRODUCTION_ENV)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'db.example.test'


def test_production_settings_refuse_to_boot_without_a_database():
    env = {key: value for key, value in PRODUCTION_ENV.items() if key != 'DJANGO_DATABASE_URL'}

    result = _load_settings(env)

    assert result.returncode != 0
    assert 'DJANGO_DATABASE_URL is required' in result.stderr


def test_production_settings_refuse_to_boot_with_an_unregistered_payment_gateway():
    result = _load_settings(PRODUCTION_ENV | {'DJANGO_PAYMENT_GATEWAY': 'omise'})

    assert result.returncode != 0
    assert "no payment gateway adapter is registered for ['omise']" in result.stderr


def test_production_settings_refuse_a_secret_key_too_short_to_sign_jwts():
    result = _load_settings(PRODUCTION_ENV | {'DJANGO_SECRET_KEY': 'x' * 31})

    assert result.returncode != 0
    assert 'DJANGO_SECRET_KEY must be at least 32 bytes' in result.stderr
