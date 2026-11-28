from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase
from django.urls import reverse

from catalog.models import Category, Product
from dlux.models import SystemSettings
from public_catalog.homepage import (
    HOMEPAGE_DEFAULTS, get_homepage_config, localize, normalize_sections,
    resolve_homepage, set_homepage_config,
)
from public_catalog.models import PublicCatalogListing
from public_catalog.settings import set_public_catalog_config

from .test_public_split import configure_dlux_public_split

User = get_user_model()


class HomepageConfigTests(TestCase):
    def tearDown(self):
        set_homepage_config(dict(HOMEPAGE_DEFAULTS))

    def test_normalize_sections_drops_unknown_and_appends_new(self):
        result = normalize_sections([
            {"key": "contact", "enabled": False, "variant": "compact"},
            {"key": "bogus", "enabled": True},
            {"key": "featured", "enabled": True, "variant": "not-real"},
        ])
        keys = [s["key"] for s in result]
        # stored order first (known keys), then remaining defaults appended
        self.assertEqual(keys[:2], ["contact", "featured"])
        self.assertEqual(set(keys), {"featured", "categories", "services", "story", "contact"})
        self.assertFalse(result[0]["enabled"])  # contact stayed disabled
        self.assertEqual(result[0]["variant"], "compact")
        self.assertEqual(result[1]["variant"], "grid")  # bad variant fell back

    def test_localized_fields_store_per_language_and_resolve_with_fallback(self):
        cfg = set_homepage_config({"hero_title": {"en": "Secure space", "ar": "مساحة"}})
        self.assertEqual(cfg["hero_title"], {"en": "Secure space", "ar": "مساحة"})
        self.assertEqual(resolve_homepage(cfg, lang="en")["hero_title"], "Secure space")
        self.assertEqual(resolve_homepage(cfg, lang="ar")["hero_title"], "مساحة")
        # empty language falls back to any filled value
        cfg = set_homepage_config({"hero_title": {"en": "Only EN", "ar": ""}})
        self.assertEqual(resolve_homepage(cfg, lang="ar")["hero_title"], "Only EN")
        # legacy plain-string config migrates into the default-language slot
        cfg = set_homepage_config({"hero_subtitle": "Legacy string"})
        self.assertEqual(localize(cfg["hero_subtitle"], "en", "en"), "Legacy string")

    def test_accent_and_overlay_are_sanitised(self):
        cfg = set_homepage_config({"accent": "0EA5E9", "accent_secondary": "14B8A6", "hero_overlay": "250"})
        self.assertEqual(cfg["accent"], "#0ea5e9")
        self.assertEqual(cfg["accent_secondary"], "#14b8a6")
        self.assertEqual(cfg["hero_overlay"], 100)
        cfg = set_homepage_config({"accent": "not-a-color", "accent_secondary": "not-a-color", "hero_overlay": "-5"})
        self.assertEqual(cfg["accent"], "")
        self.assertEqual(cfg["accent_secondary"], "")
        self.assertEqual(cfg["hero_overlay"], 0)

    def test_visual_choice_fields_fall_back_to_defaults(self):
        cfg = set_homepage_config({
            "style_preset": "showroom",
            "hero_layout": "mosaic",
            "hero_height": "immersive",
            "hero_focus": "right",
            "nav_treatment": "solid",
            "card_treatment": "spec",
            "section_density": "compact",
            "background_treatment": "linework",
            "motion_level": "none",
        })
        self.assertEqual(cfg["style_preset"], "showroom")
        self.assertEqual(cfg["hero_layout"], "mosaic")
        self.assertEqual(cfg["motion_level"], "none")
        cfg = set_homepage_config({
            "style_preset": "wrong",
            "hero_layout": "wrong",
            "hero_height": "wrong",
            "hero_focus": "wrong",
            "nav_treatment": "wrong",
            "card_treatment": "wrong",
            "section_density": "wrong",
            "background_treatment": "wrong",
            "motion_level": "wrong",
        })
        self.assertEqual(cfg["style_preset"], "signature")
        self.assertEqual(cfg["hero_layout"], "poster")
        self.assertEqual(cfg["hero_height"], "balanced")
        self.assertEqual(cfg["hero_focus"], "center")
        self.assertEqual(cfg["nav_treatment"], "glass")
        self.assertEqual(cfg["card_treatment"], "showcase")
        self.assertEqual(cfg["section_density"], "comfortable")
        self.assertEqual(cfg["background_treatment"], "clean")
        self.assertEqual(cfg["motion_level"], "subtle")


class HomepageBuilderViewTests(TestCase):
    def setUp(self):
        configure_dlux_public_split()
        self.admin = User.objects.create_superuser("hp_admin", "a@example.com", "x")
        self.client = Client()
        self.client.force_login(self.admin)
        cat = Category.objects.create(name="Locks")
        self.product = Product.objects.create(
            name="Deadbolt", category=cat, cost_usd=Decimal("5"), price_usd=Decimal("10"),
            track_stock=True, stock_qty=Decimal("4"),
        )
        PublicCatalogListing.objects.create(product=self.product, is_published=True, is_featured=True)

    def tearDown(self):
        set_homepage_config(dict(HOMEPAGE_DEFAULTS))
        set_public_catalog_config({"homepage_enabled": True, "shop_enabled": True})
        cache.delete("SystemSettings")

    def test_builder_page_renders(self):
        resp = self.client.get(reverse("public_catalog_staff:homepage_builder"))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn("data-hpb-frame", html)
        self.assertIn("data-hpb-sections", html)
        self.assertIn("preview=1", html)
        self.assertIn("preview=1&lang=", html)
        self.assertIn('name="style_preset"', html)
        self.assertIn("data-section-variant", html)
        self.assertIn('data-viewport="tablet"', html)
        self.assertNotIn("dlux_app_settings_modal", html)

    def test_save_persists_localized_hero_accent_and_section_order(self):
        resp = self.client.post(reverse("public_catalog_staff:homepage_save"), {
            "hero_title__en": "Secure your space",
            "hero_title__ar": "مساحة آمنة",
            "hero_media": "gradient",
            "hero_overlay": "70",
            "style_preset": "precision",
            "hero_layout": "center",
            "hero_height": "compact",
            "hero_focus": "top",
            "nav_treatment": "quiet",
            "card_treatment": "minimal",
            "section_density": "compact",
            "background_treatment": "grid",
            "motion_level": "none",
            "accent": "#0ea5e9",
            "accent_secondary": "#14b8a6",
            "featured_heading__en": "Our picks",
            "sections": '[{"key":"story","enabled":true,"variant":"banner"},{"key":"featured","enabled":true,"variant":"rail"}]',
        })
        self.assertEqual(resp.status_code, 200)
        cfg = get_homepage_config()
        self.assertEqual(cfg["hero_title"]["en"], "Secure your space")
        self.assertEqual(cfg["hero_title"]["ar"], "مساحة آمنة")
        self.assertEqual(cfg["featured_heading"]["en"], "Our picks")
        self.assertEqual(cfg["hero_media"], "gradient")
        self.assertEqual(cfg["hero_overlay"], 70)
        self.assertEqual(cfg["style_preset"], "precision")
        self.assertEqual(cfg["hero_layout"], "center")
        self.assertEqual(cfg["hero_height"], "compact")
        self.assertEqual(cfg["hero_focus"], "top")
        self.assertEqual(cfg["nav_treatment"], "quiet")
        self.assertEqual(cfg["card_treatment"], "minimal")
        self.assertEqual(cfg["section_density"], "compact")
        self.assertEqual(cfg["background_treatment"], "grid")
        self.assertEqual(cfg["motion_level"], "none")
        self.assertEqual(cfg["accent"], "#0ea5e9")
        self.assertEqual(cfg["accent_secondary"], "#14b8a6")
        self.assertEqual([s["key"] for s in cfg["sections"]][:2], ["story", "featured"])
        self.assertEqual(cfg["sections"][0]["variant"], "banner")
        self.assertEqual(cfg["sections"][1]["variant"], "rail")

    def test_landing_reflects_config(self):
        set_homepage_config({
            "hero_title": "Secure your space", "hero_media": "gradient",
            "style_preset": "showroom", "hero_layout": "center", "hero_height": "immersive",
            "hero_focus": "bottom", "nav_treatment": "solid", "card_treatment": "spec",
            "section_density": "compact", "background_treatment": "diagonal", "motion_level": "lively",
            "accent": "#0ea5e9", "accent_secondary": "#14b8a6", "story_heading": "Who we are",
            "sections": [{"key": "story", "enabled": True, "variant": "banner"}, {"key": "featured", "enabled": True, "variant": "rail"}],
        })
        html = self.client.get(reverse("public_catalog:landing")).content.decode()
        self.assertIn("Secure your space", html)
        self.assertIn('"--public-accent": "#0ea5e9"', html)
        self.assertIn('"--public-accent-2": "#14b8a6"', html)
        self.assertIn("public-style--showroom", html)
        self.assertIn("public-bg--diagonal", html)
        self.assertIn("public-nav--solid", html)
        self.assertIn("public-cardstyle--spec", html)
        self.assertIn("public-density--compact", html)
        self.assertIn("public-motion--lively", html)
        self.assertIn("public-hero--gradient", html)
        self.assertIn("public-hero-layout--center", html)
        self.assertIn("public-hero-height--immersive", html)
        self.assertIn("public-hero-focus--bottom", html)
        self.assertIn("public-story--banner", html)
        self.assertIn("public-card-grid--rail", html)
        self.assertIn("Who we are", html)

    def test_mosaic_hero_falls_back_without_multiple_images(self):
        set_homepage_config({"hero_layout": "mosaic", "hero_media": "custom", "hero_image": "/media/one.jpg"})
        html = self.client.get(reverse("public_catalog:landing")).content.decode()
        self.assertIn("public-hero-layout--poster", html)
        self.assertNotIn("public-hero-layout--mosaic", html)

    def test_public_language_toggle_switches_landing_content(self):
        set_homepage_config({"hero_title": {"en": "Secure space", "ar": "مساحة آمنة"}})
        anon = Client()
        en = anon.get(reverse("public_catalog:landing") + "?lang=en").content.decode()
        self.assertIn("public-lang", en)          # toggle rendered on the public header
        self.assertIn('lang="en"', en)
        self.assertIn("Secure space", en)
        ar = anon.get(reverse("public_catalog:landing") + "?lang=ar").content.decode()
        self.assertIn("مساحة آمنة", ar)

    def test_staff_preview_language_does_not_persist_to_display_session(self):
        settings = SystemSettings.load()
        settings.default_language = "ar"
        settings.allow_user_language_override = True
        settings.languages = {
            "en": {"name": "English", "dir": "ltr"},
            "ar": {"name": "العربية", "dir": "rtl"},
        }
        settings.save()
        cache.delete("SystemSettings")
        self.admin.profile.preferences = {"language": "en"}
        self.admin.profile.save(update_fields=["preferences"])
        set_homepage_config({"hero_title": {"en": "English hero", "ar": "عنوان عربي"}})

        before = self.client.get(reverse("public_catalog_staff:homepage_builder")).content.decode()
        self.assertIn('data-active-lang="en"', before)

        preview = self.client.get(reverse("public_catalog:landing") + "?preview=1&lang=ar")
        self.assertEqual(preview.status_code, 200)
        html = preview.content.decode()
        self.assertIn('lang="ar"', html)
        self.assertIn('dir="rtl"', html)
        self.assertIn("عنوان عربي", html)

        session = self.client.session
        self.assertIsNone(session.get("lang"))
        self.assertIsNone(session.get("dlux_force_language_preview"))
        after = self.client.get(reverse("public_catalog_staff:homepage_builder")).content.decode()
        self.assertIn('data-active-lang="en"', after)

    def test_staff_preview_bypasses_offline_gate(self):
        set_public_catalog_config({"homepage_enabled": False})
        anon = Client()
        landing = anon.get(reverse("public_catalog:landing"))
        self.assertEqual(landing.status_code, 503)
        self.assertNotIn('<header class="public-nav"', landing.content.decode())  # bare coming-soon, no header bar
        self.assertEqual(anon.get(reverse("public_catalog:landing") + "?preview=1").status_code, 503)
        # authed staff with permission may preview the offline homepage
        self.assertEqual(self.client.get(reverse("public_catalog:landing") + "?preview=1").status_code, 200)

    def test_get_on_save_is_silent_no_op(self):
        resp = self.client.get(reverse("public_catalog_staff:homepage_save"))
        self.assertEqual(resp.status_code, 204)

    def test_save_requires_change_permission(self):
        plain = User.objects.create_user("hp_plain", password="x")
        client = Client()
        client.force_login(plain)
        resp = client.post(reverse("public_catalog_staff:homepage_save"), {"hero_title": "x"})
        self.assertEqual(resp.status_code, 403)
