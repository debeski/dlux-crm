from django.core.cache import cache
from django.db import migrations


# 0001 seeded the original retailer's name. Blank lets DLux fall back to the
# store's own system name; values a store has since edited are left alone.
LEGACY_VALUES = {
    "public_root_title": "Switch Libya",
    "public_root_meta_description": (
        "Smart locks, access control, installation and after-sale services from Switch Libya."
    ),
}


def clear_legacy_public_defaults(apps, schema_editor):
    SystemSettings = apps.get_model("dlux", "SystemSettings")
    for settings_obj in SystemSettings.objects.all():
        config = settings_obj.public_root_config
        if not isinstance(config, dict):
            continue
        changed = False
        for key, legacy in LEGACY_VALUES.items():
            if config.get(key) == legacy:
                config[key] = ""
                changed = True
        if changed:
            settings_obj.public_root_config = config
            settings_obj.save(update_fields=["public_root_config"])
    cache.delete("SystemSettings")


class Migration(migrations.Migration):

    dependencies = [
        ("public_catalog", "0002_listing_image_asset"),
    ]

    operations = [
        migrations.RunPython(clear_legacy_public_defaults, migrations.RunPython.noop),
    ]
