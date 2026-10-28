from pathlib import Path

import environ


#: Settings read `configs.bool('DEBUG')`; the environment variable is `DJANGO_DEBUG`.
DJANGO_ENV_PREFIX = 'DJANGO_'


class DjangoEnvironPrefix(environ.Env):
    def __init__(self, prefix: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.prefix = prefix


def load_configs(base_dir: Path) -> DjangoEnvironPrefix:
    configs = DjangoEnvironPrefix(prefix=DJANGO_ENV_PREFIX)
    if configs.bool('READ_DOT_ENV_FILE', default=True):
        # Variables already in the process environment take precedence over `.env`.
        configs.read_env(str(base_dir / '.env'))
    return configs
