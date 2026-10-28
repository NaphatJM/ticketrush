import os


bind = f'0.0.0.0:{os.getenv("PORT", "8000")}'
workers = int(os.getenv('GUNICORN_WORKERS', '2'))
threads = int(os.getenv('GUNICORN_THREADS', '4'))
worker_class = 'gthread'
timeout = int(os.getenv('GUNICORN_TIMEOUT', '30'))
graceful_timeout = 20
keepalive = 5
max_requests = 1000
max_requests_jitter = 50
accesslog = '-'
errorlog = '-'
