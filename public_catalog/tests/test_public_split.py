import json
import re
from decimal import Decimal
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core import mail
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from catalog.models import Product, ProductVariant
from dlux.models import SystemSettings
from finance.models import ExchangeRate
from public_catalog.models import PublicCatalogListing, PublicContactMessage
from public_catalog.settings import PUBLIC_CATALOG_NS


User = get_user_model()


def configure_dlux_public_split():
    settings = SystemSettings.load()
    settings.is_configured = True
    settings.home_url = "/staff/workspace/"
    settings.public_root = True
    settings.public_root_split_enabled = True
    settings.public_root_url = "/"
    settings.public_root_title = "Switch Libya"
    settings.public_root_meta_description = (
        "Smart locks, access control, installation and after-sale services from Switch Libya."
    )
    settings.show_titlebar_on_public = False
    settings.show_sidebar_on_public = False
    settings.save()
    return settings


def configure_public_contact_email(email="shop@example.com"):
    settings = SystemSettings.load()
    extra = dict(settings.extra_config or {})
    app = dict(extra.get("app") or {})
    cfg = dict(app.get(PUBLIC_CATALOG_NS) or {})
    cfg["contact_email"] = email
    app[PUBLIC_CATALOG_NS] = cfg
    extra["app"] = app
    settings.extra_config = extra
    settings.save(update_fields=["extra_config"])
    cache.delete("SystemSettings")


class PublicStaffSplitTests(TestCase):
    def setUp(self):
        cache.delete("SystemSettings")
        configure_dlux_public_split()

    def tearDown(self):
        cache.delete("SystemSettings")

    def test_internal_url_names_reverse_under_staff(self):
        self.assertEqual(reverse("login"), "/staff/accounts/login/")
        self.assertEqual(reverse("logout"), "/staff/accounts/logout/")
        self.assertEqual(reverse("common:workspace_dashboard"), "/staff/workspace/")
        self.assertEqual(reverse("catalog:product_list"), "/staff/catalog/")
        self.assertEqual(
            reverse("update_app_preference", kwargs={"namespace": "switch_pos.workspace_dashboard.v1"}),
            "/staff/sys/api/preferences/app/switch_pos.workspace_dashboard.v1/",
        )

    def test_staff_routes_redirect_anonymous_to_staff_login(self):
        response = self.client.get(reverse("common:workspace_dashboard"))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"],
            "/staff/accounts/login/?next=/staff/workspace/",
        )

    def test_staff_entry_login_logout_flow_uses_staff_home_and_public_logout(self):
        user = User.objects.create_user("staffer", password="password12345")
        client = Client()

        entry_response = client.get("/staff/")
        self.assertEqual(entry_response.status_code, 302)
        self.assertEqual(entry_response["Location"], reverse("login"))

        login_response = client.post(
            reverse("login"),
            {"username": "staffer", "password": "password12345"},
        )
        self.assertEqual(login_response.status_code, 302)
        self.assertEqual(login_response["Location"], "/staff/workspace/")

        staff_entry_response = client.get("/staff/")
        self.assertEqual(staff_entry_response.status_code, 302)
        self.assertEqual(staff_entry_response["Location"], reverse("common:workspace_dashboard"))

        logout_response = client.post(reverse("logout"))
        self.assertEqual(logout_response.status_code, 302)
        self.assertEqual(logout_response["Location"], "/")

    def test_public_landing_and_shop_are_anonymous_accessible_without_staff_chrome(self):
        for path in ["/", reverse("public_catalog:shop")]:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
            html = response.content.decode()
            self.assertIn("public-shell", html)
            self.assertIn("public_catalog/css/public_catalog.css?v=20260714l", html)
            self.assertIn("public_catalog/js/public_catalog.js?v=20260714l", html)
            self.assertIn('data-public-modal-size="fullscreen"', html)
            self.assertNotIn("Staff sign in", html)
            self.assertNotIn(">Staff</a>", html)
            self.assertNotIn("workspace-shell", html)
            self.assertNotIn("data-widget-id=", html)
            self.assertNotIn("/staff/app-modals/", html)

    def test_public_catalog_omits_internal_product_fields_and_exact_stock(self):
        ExchangeRate.objects.create(rate=Decimal("6.50"))
        product = Product.objects.create(
            name="Smart Lock Alpha",
            description="Public deadbolt description.",
            cost_usd=Decimal("4.00"),
            markup_percent=Decimal("125.00"),
            price_usd=Decimal("9.00"),
            stock_qty=Decimal("7.00"),
            reorder_level=Decimal("2.00"),
            barcode="BARCODE-SECRET",
        )
        ProductVariant.objects.create(
            product=product,
            color=Product.COLOR_BLACK,
            size="Matte",
            stock_qty=Decimal("3.00"),
        )
        listing = PublicCatalogListing.objects.create(
            product=product,
            public_title="Public Smart Lock",
            public_summary="Public-safe summary.",
            public_body="Public-safe detail.",
            installation_notes="Installation quoted after site check.",
            warranty_notes="Warranty terms available on request.",
            is_published=True,
            is_featured=True,
        )

        shop_html = self.client.get(reverse("public_catalog:shop")).content.decode()
        detail_html = self.client.get(listing.get_absolute_url()).content.decode()
        modal_response = self.client.get(reverse("public_catalog:item_modal", args=[listing.slug]))
        modal_payload = json.loads(modal_response.content.decode())
        combined = "\n".join([shop_html, detail_html, modal_payload["html"]])

        self.assertEqual(modal_response.status_code, 200)
        self.assertIn("Public Smart Lock", combined)
        self.assertIn("58.50 LYD", combined)
        self.assertIn("Available", combined)
        self.assertIn("Black / Matte", combined)
        self.assertIn("public-card__status", shop_html)
        self.assertIn("public-detail-facts", detail_html)
        self.assertIn("public-modal-section", modal_payload["html"])
        self.assertNotIn(product.sku, combined)
        self.assertNotIn("BARCODE-SECRET", combined)
        self.assertNotIn("Import Cost", combined)
        self.assertNotIn("Markup", combined)
        self.assertNotIn("Stock Qty", combined)
        self.assertNotIn("7.00", combined)
        self.assertNotIn("3.00", combined)
        self.assertNotIn("/staff/app-modals/", combined)

    def test_public_storefront_chrome_and_labels_follow_visitor_language(self):
        ExchangeRate.objects.create(rate=Decimal("6.50"))
        product = Product.objects.create(
            name="Smart Lock Beta",
            cost_usd=Decimal("4.00"),
            price_usd=Decimal("9.00"),
            stock_qty=Decimal("7.00"),
            reorder_level=Decimal("2.00"),
        )
        listing = PublicCatalogListing.objects.create(product=product, is_published=True, is_featured=True)

        visitor = Client()
        shop_html = visitor.get(reverse("public_catalog:shop") + "?lang=ar").content.decode()
        landing_html = visitor.get(reverse("public_catalog:landing") + "?lang=ar").content.decode()
        modal_html = json.loads(visitor.get(reverse("public_catalog:item_modal", args=[listing.slug])).content)["html"]
        contact_html = json.loads(visitor.get(reverse("public_catalog:contact_modal")).content)["html"]
        arabic = "\n".join([shop_html, landing_html, modal_html, contact_html])

        for text in ["ابحث في المنتجات والخدمات", "نظرة سريعة", "عرض الصفحة", "متوفر", "منتج",
                     "التوفر", "أرسل طلباً", "إرسال الرسالة", "جاهزة لعرضها على العملاء"]:
            self.assertIn(text, arabic)
        for text in ["Search products and services", "Quick view", "View page", "Send message",
                     "Ready for customer viewing", ">Availability<"]:
            self.assertNotIn(text, arabic)

        english = visitor.get(reverse("public_catalog:shop") + "?lang=en").content.decode()
        self.assertIn("Quick view", english)
        self.assertIn("Available", english)

    def test_public_shop_excludes_unpublished_and_inactive_sources(self):
        active = Product.objects.create(name="Visible Lock", price_usd=Decimal("10.00"), stock_qty=Decimal("2.00"))
        inactive = Product.objects.create(
            name="Inactive Lock",
            price_usd=Decimal("10.00"),
            stock_qty=Decimal("2.00"),
            is_active=False,
        )
        hidden = Product.objects.create(name="Hidden Lock", price_usd=Decimal("10.00"), stock_qty=Decimal("2.00"))
        PublicCatalogListing.objects.create(product=active, is_published=True)
        PublicCatalogListing.objects.create(product=inactive, is_published=True)
        PublicCatalogListing.objects.create(product=hidden, is_published=False)

        html = self.client.get(reverse("public_catalog:shop")).content.decode()

        self.assertIn("Visible Lock", html)
        self.assertNotIn("Inactive Lock", html)
        self.assertNotIn("Hidden Lock", html)

    def test_public_shop_stylesheet_uses_storefront_layout_contract(self):
        css_path = Path(__file__).resolve().parents[1] / "static" / "public_catalog" / "css" / "public_catalog.css"
        css = css_path.read_text(encoding="utf-8")

        self.assertIn(".public-hero__slide", css)
        self.assertIn(".public-card__status", css)
        self.assertIn("grid-template-columns: repeat(auto-fill, minmax(245px, 1fr))", css)
        self.assertIn(".public-cardstyle--spec .public-card", css)
        self.assertIn("grid-template-columns: 6rem minmax(0, 1fr)", css)
        self.assertIn(".public-cardstyle--minimal .public-card__media", css)
        self.assertIn("display: none", css)
        self.assertIn(".public-density--compact .public-section__head", css)
        self.assertIn(".public-bg--grid", css)
        self.assertIn(".public-bg--grid::before", css)
        self.assertIn("mask-size: 112px 112px", css)
        self.assertIn("opacity: .30", css)
        self.assertIn("stroke-width='1.6'", css)
        self.assertIn("M18 0V18H58V42H90", css)
        self.assertIn("M18 18V74H112", css)
        self.assertIn("M0 58H34V90H74V112", css)
        self.assertIn("transparent 3px 96px", css)
        self.assertIn(".public-bg--linework", css)
        self.assertIn("linear-gradient(25deg", css)
        self.assertIn("linear-gradient(145deg", css)
        self.assertIn("calc(76% + 1px)", css)
        self.assertIn(".public-style--showroom .public-card__media", css)
        self.assertIn(".public-style--precision .public-kicker", css)
        self.assertIn('"Courier New", Courier, monospace', css)
        self.assertIn(".public-style--editorial .public-hero h1", css)
        self.assertIn('Georgia, "Times New Roman", serif', css)
        self.assertIn(":root.theme-aether .public-shell", css)
        self.assertIn(".public-contact-modal", css)
        self.assertNotIn("border-radius: .9rem", css)

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="no-reply@example.com",
    )
    def test_public_contact_modal_sends_email_idempotently(self):
        configure_public_contact_email("sales@example.com")
        get_response = self.client.get(reverse("public_catalog:contact_modal"), HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        payload = json.loads(get_response.content.decode())
        self.assertEqual(get_response.status_code, 200)
        self.assertIn("public-contact-form", payload["html"])
        match = re.search(r'name="idempotency_key" value="([^"]+)"', payload["html"])
        self.assertIsNotNone(match)
        key = match.group(1)
        data = {
            "idempotency_key": key,
            "source_path": "/",
            "company": "",
            "name": "Public Buyer",
            "email": "buyer@example.com",
            "phone": "+218900000000",
            "subject": "Smart lock installation",
            "message": "Please quote installation and warranty.",
        }

        first = self.client.post(reverse("public_catalog:contact_modal"), data, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        second = self.client.post(reverse("public_catalog:contact_modal"), data, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        success = self.client.get(reverse("public_catalog:contact_modal"), HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        success_payload = json.loads(success.content.decode())

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(PublicContactMessage.objects.count(), 1)
        msg = PublicContactMessage.objects.get()
        self.assertEqual(msg.idempotency_key, key)
        self.assertEqual(msg.email_status, PublicContactMessage.STATUS_SENT)
        self.assertEqual(msg.email_recipient, "sales@example.com")
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Smart lock installation", mail.outbox[0].subject)
        self.assertIn("buyer@example.com", mail.outbox[0].body)
        self.assertIn("Message received", success_payload["html"])

    def test_public_and_staff_entry_routes_are_excluded_from_dlux_sidebar_discovery(self):
        from dlux.discovery import bump_sidebar_cache_version, discover_sidebar_catalog

        bump_sidebar_cache_version()
        names = {entry["url_name"] for entry in discover_sidebar_catalog(include_system_items=True)}

        self.assertNotIn("public_catalog:landing", names)
        self.assertNotIn("public_catalog:shop", names)
        self.assertNotIn("public_catalog:contact_modal", names)
        self.assertNotIn("staff_entry", names)
