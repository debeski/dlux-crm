"""``{% asset 'app/css/file.css' %}``: a static URL that changes when the file does.

Caddy serves static files as ``immutable`` for a year, so a URL must change
whenever its file changes or browsers keep the old copy until a hard reload.
Hand-written ``?v=`` stamps were forgotten; ``dlux_static`` versions by the
DjangoLux release, which a project release does not move. This versions by a
short hash of the file's contents, read once per file change.
"""
import hashlib
import os

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


@register.simple_tag
def asset(path):
    url = static(path)
    digest = _content_hash(path)
    return f"{url}{'&' if '?' in url else '?'}v={digest}" if digest else url
