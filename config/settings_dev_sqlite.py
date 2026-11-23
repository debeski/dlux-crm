"""
Dev-only settings overlay for LOCAL verification without Postgres/Redis.

NOT for production. Run e.g.:
    python manage.py migrate --settings=config.settings_dev_sqlite
"""
import tempfile
from pathlib import Path

from .settings import *  # noqa: F401,F403

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": str(Path(tempfile.gettempdir()) / "sales_crm_dev.sqlite3"),
    }
}

CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
}

SESSION_ENGINE = "django.contrib.sessions.backends.db"

ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]
