import json
import re
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from catalog.models import Product


User = get_user_model()
ENABLED = {
    "automotive": {
        "enabled": True,
        "criteria": {
            "generation_chassis": True, "engine": True, "fuel_type": True,
            "trim": True, "transmission": True, "position": True,
        },
    },
}


class ArabicUiTests(TestCase):
    """Strings the Arabic walkthrough found still in English."""

    def setUp(self):
        from dlux.models import SystemSettings

        settings = SystemSettings.load()
        settings.is_configured = True
        settings.save(update_fields=["is_configured"])
        self.client.force_login(User.objects.create_superuser("ar-admin", "ar@example.com", "x"))
        session = self.client.session
        session["lang"] = "ar"
        session["dlux_force_language_preview"] = True
        session.save()

    def get(self, url):
        with patch("automotive.settings.get_optional_enhancements_config", return_value=ENABLED):
            return self.client.get(url)

    @staticmethod
    def options(html, name):
        select = re.search(rf'<select name="{name}".*?</select>', html, re.S).group(0)
        return re.findall(r'<option value="([^"]+)"[^>]*>([^<]*)</option>', select)

    def test_filter_options_survive_the_ribbon(self):
        units = dict(self.options(self.get(reverse("catalog:product_list")).content.decode(), "unit"))
        self.assertEqual(units[Product.UNIT_PIECE], "قطعة")
        fuels = dict(self.options(self.get(reverse("automotive:engine_list")).content.decode(), "fuel_type"))
        self.assertEqual(fuels["gasoline"], "بنزين")

    def test_sidebar_hidden_routes_get_translated_breadcrumbs(self):
        from common.context_processors import ROUTE_CRUMBS
        from dlux.translations import get_strings

        strings = get_strings("ar")
        for route, crumbs in ROUTE_CRUMBS.items():
            for crumb in crumbs:
                self.assertRegex(strings.get(crumb["label_key"], ""), r"[؀-ۿ]", route)
        response = self.get(reverse("automotive:make_list"))
        self.assertEqual(response.context["dlux_navbar_crumbs"], ROUTE_CRUMBS["automotive:make_list"])

    def test_product_image_picker_has_a_translated_tag(self):
        product = Product.objects.create(name="Pads")
        url = reverse("scoped_modal_manager", args=["catalog", "product", product.pk])
        html = json.loads(self.get(url).content)["html"]
        tag = re.search(r"data-dlux-file-label>\s*([^<]*?)\s*<", html).group(1)
        self.assertEqual(tag, "الصورة")
