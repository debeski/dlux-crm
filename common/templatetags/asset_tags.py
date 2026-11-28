"""``{% asset 'app/css/file.css' %}``: a static URL that changes when the file does.

Caddy serves static files as ``immutable`` for a year, so a URL must change
whenever its file changes. DjangoLux's ``VersionedStaticFilesStorage`` (set by
``dlux_settings()``) already puts ``v=<DjangoLux version>-<project version>`` on
every static URL, plus the file's modification time in DEBUG, so this tag
returns that URL unchanged. Only when a project runs without that storage
(``DLUX_VERSIONED_STATIC = False`` or another backend) does it add a short hash
of the file's contents, read once per file change.
"""
import hashlib
import os
from urllib.parse import urlsplit

from django import template
from django.contrib.staticfiles import finders
from django.templatetags.static import static

register = template.Library()

_HASHES = {}


def _content_hash(path):
    source = finders.find(path)
    if not source:
        return ""
    try:
        stamp = os.stat(source).st_mtime_ns
    except OSError:
        return ""
    cached = _HASHES.get(path)
    if cached and cached[0] == stamp:
        return cached[1]
    with open(source, "rb") as handle:
        digest = hashlib.sha256(handle.read()).hexdigest()[:12]
    _HASHES[path] = (stamp, digest)
    return digest


def _has_version(url):
    return any(part == "v" or part.startswith("v=") for part in urlsplit(url).query.split("&") if part)


@register.simple_tag
def asset(path):
    url = static(path)
    if _has_version(url):
        return url
    digest = _content_hash(path)
    return f"{url}{'&' if '?' in url else '?'}v={digest}" if digest else url
