"""The CRM options "Public site" switch: off makes the install staff-only."""
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from catalog.models import Product
from common.permission_visibility import hidden_feature_permissions
from public_catalog.models import PublicCatalogListing
from public_catalog.settings import get_public_catalog_config, set_public_catalog_config
from public_catalog.tests.test_public_split import configure_dlux_public_split

User = get_user_model()


class PublicSiteSwitchTests(TestCase):
    def setUp(self):
        cache.delete("SystemSettings")
        configure_dlux_public_split()
        self.addCleanup(cache.delete, "SystemSettings")
        product = Product.objects.create(name="Pump", price_usd=10)
        self.listing = PublicCatalogListing.objects.create(product=product, is_published=True)
        self.admin = User.objects.create_superuser("site-admin", "site@example.com", "x")

    def switch_off(self):
        set_public_catalog_config({"enabled": False})
        cache.delete("SystemSettings")

    def test_on_by_default(self):
        self.assertTrue(get_public_catalog_config()["enabled"])
        self.assertEqual(self.client.get(reverse("public_catalog:shop")).status_code, 200)

    def test_off_sends_public_pages_to_the_staff_entry(self):
        self.switch_off()
        for url in (reverse("public_catalog:landing"), reverse("public_catalog:shop"),
                    reverse("public_catalog:item_detail", args=[self.listing.slug])):
            response = self.client.get(url)
            self.assertRedirects(response, reverse("staff_entry"), fetch_redirect_response=False, msg_prefix=url)

    def test_off_closes_the_public_modals(self):
        self.switch_off()
        self.assertEqual(self.client.get(reverse("public_catalog:item_modal", args=[self.listing.slug])).status_code, 404)
        self.assertEqual(self.client.get(reverse("public_catalog:contact_modal")).status_code, 404)
        self.assertEqual(self.client.post(reverse("public_catalog:contact_modal"), {"name": "x"}).status_code, 404)

    def test_off_closes_the_builders(self):
        self.client.force_login(self.admin)
        self.switch_off()
        for name in ("public_catalog_staff:builder", "public_catalog_staff:homepage_builder"):
            self.assertRedirects(self.client.get(reverse(name)), reverse("staff_entry"), fetch_redirect_response=False)
        response = self.client.post(reverse("public_catalog_staff:builder_toggle_publish"), {"kind": "product", "id": 1})
        self.assertEqual(response.status_code, 404)
        self.listing.refresh_from_db()
        self.assertTrue(self.listing.is_published, "nothing is unpublished while the site is off")

    def test_off_hides_the_builders_from_the_sidebar(self):
        from common.context_processors import crm_context

        self.client.force_login(self.admin)
        self.switch_off()
        request = self.client.get(reverse("staff_entry"), follow=True).wsgi_request
        request.user = self.admin
        entries = repr(crm_context(request).get("sidebar_entries"))
        self.assertNotIn("public_catalog_staff:", entries)
        self.assertNotIn("/staff/shop-builder/", entries)

    def test_off_hides_public_catalog_permissions(self):
        from django.contrib.auth.models import Permission

        def hidden_apps():
            condition = hidden_feature_permissions()
            if condition is None:
                return set()
            return set(Permission.objects.filter(condition).values_list("content_type__app_label", flat=True))

        self.assertNotIn("public_catalog", hidden_apps())
        self.switch_off()
        self.assertIn("public_catalog", hidden_apps())

    def test_switching_back_on_restores_the_site_as_it_was(self):
        set_public_catalog_config({"shop_title": "Heavy Parts", "shop_enabled": True})
        self.switch_off()
        set_public_catalog_config({"enabled": True})
        cache.delete("SystemSettings")
        cfg = get_public_catalog_config()
        self.assertEqual((cfg["shop_title"], cfg["shop_enabled"]), ("Heavy Parts", True))
        self.assertEqual(self.client.get(reverse("public_catalog:shop")).status_code, 200)
        self.listing.refresh_from_db()
        self.assertTrue(self.listing.is_published)
