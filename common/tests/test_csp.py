from datetime import date
from decimal import Decimal
from html.parser import HTMLParser
from unittest.mock import patch

from csp.constants import NONCE, NONE, SELF, UNSAFE_EVAL, UNSAFE_INLINE
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from catalog.models import Product, PurchaseInvoice, StockTake, Supplier
from public_catalog.tests.test_public_split import configure_dlux_public_split
from sales.models import Invoice, Payment


class _MarkupAudit(HTMLParser):
    """Collects what a strict CSP would refuse on a rendered page."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.scripts = []
        self.handlers = []
        self.style_attrs = []
        self.style_blocks = 0
        self.js_urls = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script":
            self.scripts.append(attrs)
        if tag == "style":
            self.style_blocks += 1
        for name, value in attrs.items():
            if name.startswith("on"):
                self.handlers.append(f"<{tag} {name}>")
            if name == "style":
                self.style_attrs.append(f"<{tag} style={value!r}>")
            if name in {"href", "src", "action", "formaction"} and (value or "").strip().lower().startswith("javascript:"):
                self.js_urls.append(f"<{tag} {name}>")

    handle_startendtag = handle_starttag


class ContentSecurityPolicySettingsTests(TestCase):
    def directives(self):
        return settings.CONTENT_SECURITY_POLICY["DIRECTIVES"]

    def test_script_src_is_self_and_nonce_only(self):
        script_src = self.directives()["script-src"]
        self.assertEqual(script_src, [SELF, NONCE])
        self.assertNotIn(UNSAFE_INLINE, script_src)
        self.assertNotIn(UNSAFE_EVAL, script_src)

    def test_style_src_is_self_only(self):
        self.assertEqual(self.directives()["style-src"], [SELF])

    def test_base_uri_and_object_src_are_locked(self):
        self.assertEqual(self.directives()["base-uri"], [SELF])
        self.assertEqual(self.directives()["object-src"], [NONE])

    def test_no_directive_allows_unsafe_sources(self):
        for name, sources in self.directives().items():
            self.assertNotIn(UNSAFE_INLINE, sources, name)
            self.assertNotIn(UNSAFE_EVAL, sources, name)


class RenderedPagesAreCspCleanTests(TestCase):
    """Staff and storefront pages carry nothing the policy above would block."""

    def setUp(self):
        cache.delete("SystemSettings")
        configure_dlux_public_split()
        self.user = get_user_model().objects.create_superuser("csp-admin", "csp@example.com", "password12345")
        product = Product.objects.create(name="CSP Lock", cost_usd=Decimal("10.00"), price_usd=Decimal("15.00"))
        self.invoice = Invoice.objects.create(
            customer_name="CSP Buyer", status=Invoice.STATUS_ISSUED, total_lyd=Decimal("100.00"),
        )
        self.payment = Payment.objects.create(invoice=self.invoice, amount=Decimal("40.00"))
        supplier = Supplier.objects.create(name="CSP Supplier")
        self.purchase = PurchaseInvoice.objects.create(supplier=supplier, total_lyd=Decimal("50.00"))
        self.take = StockTake.objects.create(count_date=date(2026, 3, 1))
        self.product = product

    def tearDown(self):
        cache.delete("SystemSettings")

    def assertCspClean(self, path, response):
        self.assertEqual(response.status_code, 200, path)
        header = response.get("Content-Security-Policy", "")
        self.assertIn("script-src 'self' 'nonce-", header, path)
        nonce = header.split("'nonce-", 1)[1].split("'", 1)[0]
        audit = _MarkupAudit()
        audit.feed(response.content.decode())
        inline_without_nonce = [
            attrs for attrs in audit.scripts
            if not attrs.get("src") and attrs.get("type") != "application/json" and attrs.get("nonce") != nonce
        ]
        foreign_src = [
            attrs["src"] for attrs in audit.scripts
            if attrs.get("src") and not attrs["src"].startswith("/")
        ]
        self.assertEqual(inline_without_nonce, [], f"{path}: inline <script> without the page nonce")
        self.assertEqual(foreign_src, [], f"{path}: script from another origin")
        self.assertEqual(audit.handlers, [], f"{path}: inline event handlers")
        self.assertEqual(audit.js_urls, [], f"{path}: javascript: URLs")
        self.assertEqual(audit.style_attrs, [], f"{path}: style attributes")
        self.assertEqual(audit.style_blocks, 0, f"{path}: <style> blocks")

    def test_staff_pages(self):
        self.client.force_login(self.user)
        paths = [
            reverse("common:workspace_dashboard"),
            reverse("catalog:product_list"),
            reverse("catalog:purchase_invoice_create"),
            reverse("catalog:purchase_invoice_detail", args=[self.purchase.pk]),
            reverse("catalog:purchase_invoice_print", args=[self.purchase.pk]),
            reverse("catalog:opening_stock"),
            reverse("catalog:stock_take_detail", args=[self.take.pk]),
            reverse("sales:invoice_list"),
            reverse("sales:invoice_create"),
            reverse("sales:invoice_detail", args=[self.invoice.pk]),
            reverse("sales:invoice_print", args=[self.invoice.pk]),
            reverse("sales:payment_receipt", args=[self.payment.pk]),
            reverse("sales:financial_report"),
            reverse("sales:pos_till"),
        ]
        from sales import pos_views
        from sales.pos_settings import get_pos_config

        pos_config = {**get_pos_config(), "enabled": True}
        with patch.object(pos_views, "get_pos_config", return_value=pos_config):
            for path in paths:
                with self.subTest(path=path):
                    self.assertCspClean(path, self.client.get(path))

    def test_storefront_pages(self):
        for path in ["/", reverse("public_catalog:shop")]:
            with self.subTest(path=path):
                self.assertCspClean(path, self.client.get(path))

    def test_fiscal_year_picker_submits_without_an_inline_handler(self):
        self.client.force_login(self.user)
        html = self.client.get(reverse("sales:financial_report")).content.decode()
        self.assertIn("data-submit-on-change", html)
        self.assertNotIn("onchange=", html)
