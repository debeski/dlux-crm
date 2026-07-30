"""
Generated with django-lux 1.2.1.
Project name: switch-pos.
Generated on: 2026-06-22.
"""
import os
from pathlib import Path
import logging
from urllib.parse import urlparse
from csp.constants import SELF, UNSAFE_EVAL, UNSAFE_INLINE
from dlux.utils import get_secret, get_project_version
from dlux.utils import dlux_settings  # noqa: separate line so dlux_setup's literal substring check sees it and stops re-appending its block


WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

BASE_DIR = Path(__file__).resolve().parent.parent
DLUX_APP_VERSION = get_project_version(BASE_DIR)
BASE_URL = os.getenv("BASE_URL", "http://localhost")
BASE_HOSTNAME = urlparse(BASE_URL).hostname
ALLOWED_URLS = [
    url.strip()
    for url in os.getenv("ALLOWED_URLS", "").split(",")
    if url.strip()
]
ROOT_URLCONF = "config.urls"

SECRET_KEY = get_secret("DJANGO_SECRET_KEY", "DJANGO_SECRET_KEY") or "insecure-temporary-dev-only-key-change-me-now"
DEBUG = os.getenv("DEBUG_STATUS", "True").lower() == "true"

# Security & Origins configuration
is_secure = BASE_URL.startswith("https://")
is_local = BASE_HOSTNAME in ["localhost", "127.0.0.1"] or ":" in (BASE_HOSTNAME or "")

ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv(
        "ALLOWED_HOSTS",
        "web,nginx,caddy,localhost,127.0.0.1,switchlibya.ly,www.switchlibya.ly,erp.switchlibya.ly",
    ).split(",")
    if host.strip()
]

# Unified list of trusted origins for CORS and CSRF
TRUSTED_ORIGINS = list(set(
    ([BASE_URL] if BASE_URL.startswith(("http://", "https://")) else []) +
    ALLOWED_URLS +
    (['http://localhost', 'http://127.0.0.1'] if DEBUG else [])
))

CORS_ALLOW_ALL_ORIGINS = DEBUG
CORS_ALLOWED_ORIGINS = TRUSTED_ORIGINS
CSRF_TRUSTED_ORIGINS = TRUSTED_ORIGINS

SESSION_COOKIE_SECURE = is_secure
CSRF_COOKIE_SECURE = is_secure
SESSION_COOKIE_DOMAIN = None if is_local else BASE_HOSTNAME
CSRF_COOKIE_DOMAIN = None if is_local else BASE_HOSTNAME

if DEBUG:
    logging.basicConfig(level=logging.DEBUG)
else:
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

SECURE_SSL_REDIRECT = False # Always Set to False if using HAproxy
USE_X_FORWARDED_HOST = True
CSRF_FAILURE_VIEW = 'django.views.csrf.csrf_failure'
X_FRAME_OPTIONS = "SAMEORIGIN"

SESSION_ENGINE = "django.contrib.sessions.backends.cache"
SESSION_CACHE_ALIAS = "default"
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 60 * 60 * 24 * 7  # 1 week
SESSION_COOKIE_NAME = 'switch_pos_sessionid'
CSRF_COOKIE_NAME = 'switch_pos_csrftoken'
CSRF_COOKIE_SAMESITE = "Lax"
LOGIN_URL = "login"

DLUX_CONFIG = {
    "home_url": "/staff/workspace/",
    "public_root": True,
    "public_root_split_enabled": True,
    "public_root_url": "/",
    "public_root_title": "Switch Libya",
    "public_root_meta_description": "Smart locks, access control, installation and after-sale services from Switch Libya.",
    "show_titlebar_on_public": False,
    "show_sidebar_on_public": False,
}

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "csp",
    "health_check",
    "health_check.db",
    
    
    # Project-shared helpers (no models; hosts shared translations)
    "common",
    # DjangoLux generated apps start
    "finance",
    "catalog",
    "sales",
    "public_catalog",
    # DjangoLux generated apps end
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "csp.middleware.CSPMiddleware",
]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("POSTGRES_DB", "switch_pos_db"),
        "USER": os.getenv("POSTGRES_USER", "admin"),
        "PASSWORD": get_secret("POSTGRES_PASSWORD", "POSTGRES_PASSWORD") or "admin_pass",
        "HOST": os.getenv("POSTGRES_HOST", "db"),
        "PORT": os.getenv("POSTGRES_PORT", "5432"),
    }
}

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": os.getenv("REDIS_URL_DB", "redis://redis:6379/1"),
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
            "SOCKET_CONNECT_TIMEOUT": 5,
            "SOCKET_TIMEOUT": 20,
            "CONNECTION_POOL_KWARGS": {"max_connections": 50},
        },
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
TIME_ZONE = os.getenv("TIME_ZONE", "Africa/Tripoli")

CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/2")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/3")
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE

EMAIL_BACKEND = os.getenv("EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST = os.getenv("EMAIL_HOST", "")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_USE_TLS = os.getenv("EMAIL_USE_TLS", "True").lower() == "true"
EMAIL_USE_SSL = os.getenv("EMAIL_USE_SSL", "False").lower() == "true"
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = get_secret("EMAIL_HOST_PASSWORD", "EMAIL_HOST_PASSWORD") or ""
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", EMAIL_HOST_USER or "webmaster@localhost")

CONTENT_SECURITY_POLICY = {
    "DIRECTIVES": {
        "default-src": [SELF],
        "script-src": [SELF, UNSAFE_INLINE, UNSAFE_EVAL],
        "style-src": [SELF, UNSAFE_INLINE],
        "img-src": [SELF, "data:", "blob:"],
        "font-src": [SELF, "data:"],
        "connect-src": [SELF, BASE_URL],
        "frame-ancestors": [SELF],
        "form-action": [SELF],
    }
}

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

dlux_settings(globals())

# DjangoLux integration
from dlux.utils import dlux_settings
dlux_settings(globals())
