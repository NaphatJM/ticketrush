import os

from ticketrush import telemetry


bind = f'0.0.0.0:{os.getenv("PORT", "8000")}'
workers = int(os.getenv('GUNICORN_WORKERS', '2'))
threads = int(os.getenv('GUNICORN_THREADS', '4'))
worker_class = 'gthread'
timeout = int(os.getenv('GUNICORN_TIMEOUT', '30'))
graceful_timeout = 20
keepalive = 5
# Recycling forks a worker that re-imports Django; a low limit restarts workers every few seconds under load.
max_requests = int(os.getenv('GUNICORN_MAX_REQUESTS', '20000'))
max_requests_jitter = max_requests // 10
accesslog = '-'
errorlog = '-'


def post_fork(server, worker):
    telemetry.configure()
