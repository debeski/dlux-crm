"""Move the stored settings and preferences from ``switch_pos.*`` to ``sales_crm.*``.

The project's app-settings namespaces (``SystemSettings.extra_config['app']``) and
per-user preference keys (``Profile.preferences['app']``) carried the product's old
name. This renames every key with the old prefix in both JSON columns. A key that
already exists under the new name is kept and the old one dropped, so running it
on a partly moved database changes nothing it should not. The reverse operation
moves them back.
"""
from django.core.cache import cache
from django.db import migrations

OLD = "switch_pos."
NEW = "sales_crm."
APP = "app"


def _rename(bag, source, target):
    """Return ``bag`` with its ``source.*`` keys under ``target.*``, or None if unchanged."""
    if not isinstance(bag, dict):
        return None
    app = bag.get(APP)
    if not isinstance(app, dict) or not any(key.startswith(source) for key in app):
        return None
    moved = {}
    for key, value in app.items():
        if key.startswith(source):
            renamed = target + key[len(source):]
            if renamed not in app:
                moved[renamed] = value
        else:
            moved[key] = value
    return {**bag, APP: moved}


def _move(apps, source, target):
    SystemSettings = apps.get_model("dlux", "SystemSettings")
    for row in SystemSettings.objects.all():
        renamed = _rename(row.extra_config, source, target)
        if renamed is not None:
            row.extra_config = renamed
            row.save(update_fields=["extra_config"])

    Profile = apps.get_model("dlux", "Profile")
    for profile in Profile.objects.exclude(preferences={}).iterator():
        renamed = _rename(profile.preferences, source, target)
        if renamed is not None:
            profile.preferences = renamed
            profile.save(update_fields=["preferences"])

    # DjangoLux caches the settings row; drop it so the next read sees the new keys.
    cache.delete("SystemSettings")


def forwards(apps, schema_editor):
    _move(apps, OLD, NEW)


def backwards(apps, schema_editor):
    _move(apps, NEW, OLD)


class Migration(migrations.Migration):
    # After every migration that reads the old keys (catalog 0010, machinery 0002).
    dependencies = [
        ("dlux", "0030_task_runner"),
        ("catalog", "0013_opening_stock_draft"),
        ("machinery", "0004_live_name_uniqueness"),
        ("public_catalog", "0003_neutral_public_root_defaults"),
        ("automotive", "0004_vehiclemodel_alias"),
        ("finance", "0004_exchangerate_currency"),
        ("sales", "0011_invoiceitem_unit_cost_lyd"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
