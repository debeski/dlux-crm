import json
from importlib import import_module
from unittest.mock import patch

from django.apps import apps as django_apps
from django.test import TestCase

from public_catalog.homepage import HOMEPAGE_DEFAULTS
from public_catalog.settings import PUBLIC_CATALOG_DEFAULTS, get_public_catalog_config
from public_catalog.translations import DLUX_STRINGS


class NeutralBrandingTests(TestCase):
    def test_defaults_carry_no_retailer_name(self):
        text = json.dumps([HOMEPAGE_DEFAULTS, PUBLIC_CATALOG_DEFAULTS, DLUX_STRINGS], ensure_ascii=False)
        self.assertNotIn("Switch", text)
        self.assertNotIn("سويتش", text)

    def test_blank_shop_title_uses_the_store_name(self):
        identity = {"identity": {"display_name": "Parts Hub"}}
        with patch("common.identity.get_system_config", return_value=identity):
            self.assertEqual(get_public_catalog_config()["shop_title"], "Parts Hub")
            self.assertEqual(get_public_catalog_config(resolve_names=False)["shop_title"], "")

    def test_migration_clears_only_untouched_legacy_values(self):
        from dlux.models import SystemSettings

        migration = import_module("public_catalog.migrations.0003_neutral_public_root_defaults")
        settings = SystemSettings.load()
        settings.public_root_config = {
            "public_root_title": "Switch Libya",
            "public_root_meta_description": "Our own description",
        }
        settings.save(update_fields=["public_root_config"])

        migration.clear_legacy_public_defaults(django_apps, None)

        settings.refresh_from_db()
        self.assertEqual(settings.public_root_config["public_root_title"], "")
        self.assertEqual(settings.public_root_config["public_root_meta_description"], "Our own description")
