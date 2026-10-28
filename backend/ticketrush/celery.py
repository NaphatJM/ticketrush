import os

from celery import Celery


os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ticketrush.settings.settings')

app = Celery('ticketrush')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()
