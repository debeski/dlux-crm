from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import RequestFactory, TestCase
from django.urls import reverse

from dlux.utils import get_app_system_config

from dlux.options import app_settings_form_prefix

from common.dlux_options import CRM_OPTIONS_GROUP


User = get_user_model()


def field(name):
    """The posted name of a section field: "<section>-<field>" -> dlux's prefixed name."""
    section, _, rest = name.partition("-")
    return f"{app_settings_form_prefix('switch_pos.' + section)}-{rest}"


class CrmOptionsTileTests(TestCase):
    def setUp(self):
        import catalog.dlux_options  # noqa: F401
        import common.dlux_options  # noqa: F401
        import public_catalog.dlux_options  # noqa: F401
        import sales.dlux_options  # noqa: F401
        from dlux.models import SystemSettings

        settings = SystemSettings.load()
        settings.is_configured = True
        settings.save(update_fields=["is_configured"])
        self.admin = User.objects.create_superuser("crm-admin", "crm@example.com", "x")
        self.client.force_login(self.admin)
        self.url = reverse("dlux_app_settings_group_modal", args=[CRM_OPTIONS_GROUP])
        # Saved settings are cached; the test's rollback does not reach the cache.
        self.addCleanup(cache.clear)

    def request(self):
        request = RequestFactory().get("/staff/sys/options/")
        request.user = self.admin
        return request

    def post(self, **overrides):
        data = {
            "pricing-currency": "USD",
            "products_layout-default_layout": "grid",
            "public_catalog-shop_title": "Heavy Parts",
            "public_catalog-shop_subtitle": "",
            "public_catalog-contact_phone": "",
            "public_catalog-contact_whatsapp": "",
            "public_catalog-contact_email": "",
            "public_catalog-show_price": "on",
            "point_of_sale-pos_enabled": "on",
            "point_of_sale-method_cash": "on",
            "point_of_sale-max_discount_percent": "15",
            "point_of_sale-receipt_size": "58",
        }
        data.update(overrides)
        return self.client.post(self.url, {field(name): value for name, value in data.items()})

    def test_one_tile_holds_the_three_store_sections(self):
        from dlux.options import get_visible_app_settings_tiles

        tiles = {tile["id"]: tile for tile in get_visible_app_settings_tiles(self.request())}
        self.assertEqual(
            [section["namespace"] for section in tiles[CRM_OPTIONS_GROUP]["sections"]],
            ["switch_pos.pricing", "switch_pos.products_layout", "switch_pos.public_catalog", "switch_pos.point_of_sale"],
        )
        for old in ("switch_pos.products_layout", "switch_pos.public_catalog", "switch_pos.point_of_sale"):
            self.assertNotIn(old, tiles)

    def test_each_section_saves_its_own_namespace(self):
        from public_catalog.settings import set_public_catalog_config

        set_public_catalog_config({"shop_enabled": True})
        response = self.post()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json().get("success"), response.json().get("html", "")[:500])
        self.assertEqual(get_app_system_config("switch_pos.products_layout")["default_layout"], "grid")
        public = get_app_system_config("switch_pos.public_catalog")
        self.assertEqual((public["shop_title"], public["show_price"], public["show_availability"]), ("Heavy Parts", True, False))
        self.assertTrue(public["shop_enabled"], "keys the tile does not edit are kept")
        pos = get_app_system_config("switch_pos.point_of_sale")
        self.assertEqual((pos["enabled"], pos["receipt_size"], pos["max_discount_percent"]), (True, "58", "15"))
        self.assertIsNone(get_app_system_config(CRM_OPTIONS_GROUP))

    def test_an_invalid_section_saves_nothing(self):
        response = self.post(**{"point_of_sale-max_discount_percent": "150"})
        self.assertNotIn("success", response.json())
        self.assertIsNone(get_app_system_config("switch_pos.products_layout"))

    def test_modal_shows_every_section_heading(self):
        html = self.client.get(self.url).json()["html"]
        for name in ("pricing-currency", "products_layout-default_layout", "public_catalog-shop_title", "point_of_sale-receipt_size"):
            self.assertIn(f'name="{field(name)}"', html)
        self.assertIn("data-dlux-unsaved-guard", html)
        self.assertEqual(html.count("fw-bold my-3"), 4)

    def test_pos_settings_lock_while_the_till_is_off_and_keep_their_values(self):
        self.post()
        html = self.client.get(self.url).json()["html"]
        self.assertNotIn("dlux-dependent-settings is-disabled", html)
        response = self.post(**{
            "point_of_sale-pos_enabled": "", "point_of_sale-method_cash": "",
            "point_of_sale-max_discount_percent": "", "point_of_sale-receipt_size": "",
        })
        self.assertTrue(response.json().get("success"), response.json().get("html", "")[:500])
        pos = get_app_system_config("switch_pos.point_of_sale")
        self.assertEqual((pos["enabled"], pos["max_discount_percent"], pos["receipt_size"]), (False, "15", "58"))
        self.assertTrue(pos["methods"]["cash"])
        html = self.client.get(self.url).json()["html"]
        self.assertIn("dlux-dependent-settings is-disabled", html)
        self.assertIn(f'data-settings-depends-on="{field("point_of_sale-pos_enabled")}"', html)
