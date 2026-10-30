import re
from pathlib import Path

from utils.configs_loader import DJANGO_ENV_PREFIX


BACKEND = Path(__file__).resolve().parent.parent
ENV_EXAMPLE = BACKEND / '.env.example'
SETTINGS_DIR = BACKEND / 'ticketrush' / 'settings'

#: Read by tools other than Django, so they carry no prefix.
TOOL_OWNED_KEYS = frozenset({'PORT', 'GUNICORN_WORKERS', 'GUNICORN_THREADS', 'GUNICORN_TIMEOUT', 'GUNICORN_MAX_REQUESTS', 'OTEL_SERVICE_NAME'})


def _example_lines() -> list[str]:
    return ENV_EXAMPLE.read_text(encoding='utf-8').splitlines()


def _example_keys() -> set[str]:
    return {line.split('=', 1)[0] for line in _example_lines() if line and not line.startswith('#')}


def test_every_key_is_prefixed_or_tool_owned():
    unknown = {key for key in _example_keys() if not key.startswith(DJANGO_ENV_PREFIX) and key not in TOOL_OWNED_KEYS}

    assert not unknown, f'{sorted(unknown)} would be ignored by Django: add the {DJANGO_ENV_PREFIX} prefix'


def test_comments_are_on_their_own_line():
    inline = [line for line in _example_lines() if '=' in line and not line.startswith('#') and ' #' in line]

    assert not inline, 'environ reads an inline comment as part of the value'


def test_every_setting_read_from_the_environment_is_documented():
    pattern = re.compile(r"configs\.\w+\(\s*'(\w+)'")
    read = {name for path in SETTINGS_DIR.glob('*.py') for name in pattern.findall(path.read_text(encoding='utf-8'))}
    read.discard('READ_DOT_ENV_FILE')

    missing = {f'{DJANGO_ENV_PREFIX}{name}' for name in read} - _example_keys()

    assert not missing, f'{sorted(missing)} are read by settings but missing from .env.example'
