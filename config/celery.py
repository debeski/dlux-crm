"""
Generated with django-lux 1.2.1.
Project name: dlux-crm-sales.
Generated on: 2026-06-22.
"""
import os

from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_ready


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("switch_pos")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.conf.broker_connection_retry_on_startup = True
app.autodiscover_tasks()

# Periodic tasks. Refresh the external reference exchange rates (official CBL +
# black-market EAN) a few times a day so the dashboard stays current without any
# per-request scraping.
app.conf.beat_schedule = {
    "refresh-market-rates": {
        "task": "finance.tasks.refresh_market_rates",
        "schedule": crontab(minute=0, hour="*/3"),  # every 3 hours
    },
}


@worker_ready.connect
def _warm_market_rates(sender, **kwargs):
    """Populate the rate cache immediately on worker startup rather than waiting
    for the first scheduled beat run."""
    from finance.tasks import refresh_market_rates

    refresh_market_rates.delay()
