"""Web start command: refuse to boot on an unmigrated schema, then hand PID 1 to gunicorn.

Migrations run in Railway's pre-deploy command; this only checks that they did.
"""

import os
import subprocess  # noqa: S404
import sys


subprocess.check_call([sys.executable, 'manage.py', 'migrate', '--check'])  # noqa: S603

# exec so gunicorn receives SIGTERM directly and shuts down gracefully.
os.execvp('gunicorn', ['gunicorn', '--config', 'gunicorn.conf.py', 'ticketrush.wsgi:application'])  # noqa: S606, S607
