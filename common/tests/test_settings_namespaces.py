"""Stored settings and preferences move from switch_pos.* to sales_crm.*, and the
renamed identifiers stay consistent."""
import hashlib
import json
from importlib import import_module
from pathlib import Path

from django.apps import apps as django_apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

migration = import_module("common.migrations.0001_sales_crm_settings_namespaces")
ROOT = Path(__file__).resolve().parents[2]


class NamespaceMigrationTests(TestCase):
    def setUp(self):
        from dlux.models import Profile, SystemSettings

        self.settings_row = SystemSettings.load()
        self.settings_row.extra_config = {
            "app": {
                "switch_pos.pricing": {"currency": "EUR"},
                "switch_pos.point_of_sale": {"enabled": True},
                "sales_crm.point_of_sale": {"enabled": False},
                "other.namespace": {"kept": 1},
            },
            "unrelated": {"kept": True},
        }
        # A queryset update: saving the row would rename the old keys (rename_on_save).
        SystemSettings.objects.filter(pk=self.settings_row.pk).update(extra_config=self.settings_row.extra_config)
        user = get_user_model().objects.create_user("rep", password="x")
        self.profile, _ = Profile.objects.get_or_create(user=user)
        self.profile.preferences = {"app": {"switch_pos.products_layout": "grid", "switch_pos.workspace_dashboard.v1": {"order": [1]}}}
        self.profile.save(update_fields=["preferences"])

    def test_forwards_renames_both_stores_and_keeps_existing_new_keys(self):
        migration.forwards(django_apps, None)
        self.settings_row.refresh_from_db()
        self.profile.refresh_from_db()
        self.assertEqual(self.settings_row.extra_config["app"], {
            "sales_crm.pricing": {"currency": "EUR"},
            "sales_crm.point_of_sale": {"enabled": False},
            "other.namespace": {"kept": 1},
        })
        self.assertEqual(self.settings_row.extra_config["unrelated"], {"kept": True})
        self.assertEqual(self.profile.preferences["app"], {
            "sales_crm.products_layout": "grid",
            "sales_crm.workspace_dashboard.v1": {"order": [1]},
        })

    def test_the_app_reads_the_moved_value(self):
        from finance.currency import PRICING_NS
        from dlux.utils import get_app_system_config

        migration.forwards(django_apps, None)
        self.assertEqual(get_app_system_config(PRICING_NS), {"currency": "EUR"})

    def test_backwards_restores_the_old_keys(self):
        migration.forwards(django_apps, None)
        migration.backwards(django_apps, None)
        self.profile.refresh_from_db()
        self.assertIn("switch_pos.products_layout", self.profile.preferences["app"])


class StaleSettingsGuardTests(TestCase):
    """An old copy of the settings row neither survives in the cache nor saves back."""

    def setUp(self):
        from django.core.cache import cache
        from dlux.models import SystemSettings

        cache.clear()
        self.addCleanup(cache.clear)
        self.row = SystemSettings.load()

    def test_a_cached_row_with_old_keys_is_dropped(self):
        from django.core.cache import cache
        from common.settings_namespaces import CACHE_KEY, drop_stale_cache

        self.row.extra_config = {"app": {"switch_pos.pricing": {"currency": "EUR"}}}
        cache.set(CACHE_KEY, self.row)
        drop_stale_cache()
        self.assertIsNone(cache.get(CACHE_KEY))

    def test_a_current_cached_row_is_kept(self):
        from django.core.cache import cache
        from common.settings_namespaces import CACHE_KEY, drop_stale_cache

        self.row.extra_config = {"app": {"sales_crm.pricing": {"currency": "EUR"}}}
        cache.set(CACHE_KEY, self.row)
        drop_stale_cache()
        self.assertIsNotNone(cache.get(CACHE_KEY))

    def test_saving_an_old_copy_stores_the_new_keys(self):
        from dlux.models import SystemSettings

        self.row.extra_config = {"app": {"switch_pos.point_of_sale": {"enabled": True}, "sales_crm.pricing": {"currency": "EUR"}}}
        self.row.save()
        stored = SystemSettings.objects.get(pk=self.row.pk).extra_config["app"]
        self.assertEqual(stored, {"sales_crm.point_of_sale": {"enabled": True}, "sales_crm.pricing": {"currency": "EUR"}})

    def test_a_save_of_other_fields_leaves_extra_config_alone(self):
        from dlux.models import SystemSettings

        SystemSettings.objects.filter(pk=self.row.pk).update(extra_config={"app": {"switch_pos.pricing": {}}})
        row = SystemSettings.objects.get(pk=self.row.pk)
        row.save(update_fields=["is_configured"])
        self.assertIn("switch_pos.pricing", SystemSettings.objects.get(pk=row.pk).extra_config["app"])


class RenamedIdentifierTests(SimpleTestCase):
    def test_cookie_names_carry_the_product_name(self):
        self.assertEqual(settings.SESSION_COOKIE_NAME, "sales_crm_sessionid")
        self.assertEqual(settings.CSRF_COOKIE_NAME, "sales_crm_csrftoken")

    def test_no_code_uses_the_old_namespace(self):
        from automotive.settings import OPTIONAL_ENHANCEMENTS_NS
        from catalog.product_layouts import PRODUCTS_LAYOUT_NS
        from common.dlux_options import CRM_OPTIONS_GROUP
        from finance.currency import PRICING_NS
        from public_catalog.homepage import HOMEPAGE_NS
        from public_catalog.settings import PUBLIC_CATALOG_NS
        from sales.pos_settings import POS_NS

        for name in (OPTIONAL_ENHANCEMENTS_NS, PRODUCTS_LAYOUT_NS, CRM_OPTIONS_GROUP, PRICING_NS, HOMEPAGE_NS, PUBLIC_CATALOG_NS, POS_NS):
            with self.subTest(name=name):
                self.assertTrue(name.startswith("sales_crm."))

    def test_the_relay_lock_pins_every_declared_operation(self):
        """Composer's digest: sha256 of the operation as sorted, compact JSON."""
        operations = json.loads((ROOT / "relay" / "operations.json").read_text())["operations"]
        lock = json.loads((ROOT / "relay" / "operations.lock").read_text())["operations"]
        for operation in operations:
            canonical = json.dumps(operation, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
            with self.subTest(operation=operation["name"]):
                self.assertEqual(lock[operation["name"]], "sha256:" + hashlib.sha256(canonical.encode()).hexdigest())
                self.assertEqual(operation["headers"]["User-Agent"], "Mozilla/5.0 (sales-crm)")
