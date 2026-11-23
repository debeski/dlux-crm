"""Keep the ``switch_pos.*`` → ``sales_crm.*`` settings rename from coming back.

``common.0001_sales_crm_settings_namespaces`` moves the stored keys once. A process
that reads the settings row while that migration's transaction is still open (an
old container still serving, or a new one polling ``migrate --check``) can put the
old row back in DjangoLux's cache after the migration dropped it. The cached copy
lives a day, and a settings save from it would write the old keys back. So:

* ``drop_stale_cache`` removes a cached row that still has an old key; it runs
  after every migrate and when each process starts.
* ``rename_on_save`` renames old keys on any save of the row.
"""
import logging

logger = logging.getLogger(__name__)

OLD = "switch_pos."
NEW = "sales_crm."
CACHE_KEY = "SystemSettings"


def renamed_app_keys(bag):
    """``bag`` with its ``app`` keys under the new prefix, or None when nothing is old."""
    if not isinstance(bag, dict):
        return None
    app = bag.get("app")
    if not isinstance(app, dict) or not any(key.startswith(OLD) for key in app):
        return None
    moved = {}
    for key, value in app.items():
        if key.startswith(OLD):
            new_key = NEW + key[len(OLD):]
            if new_key not in app:
                moved[new_key] = value
        else:
            moved[key] = value
    return {**bag, "app": moved}


def drop_stale_cache(**kwargs):
    from django.core.cache import cache

    try:
        cached = cache.get(CACHE_KEY)
    except Exception:  # an unreadable entry is DjangoLux's to discard
        return
    if cached is not None and renamed_app_keys(getattr(cached, "extra_config", None)) is not None:
        cache.delete(CACHE_KEY)
        logger.info("Dropped a cached settings row that still had %s keys.", OLD.rstrip("."))


def rename_on_save(sender, instance, update_fields=None, **kwargs):
    if update_fields is not None and "extra_config" not in update_fields:
        return
    renamed = renamed_app_keys(instance.extra_config)
    if renamed is not None:
        instance.extra_config = renamed
