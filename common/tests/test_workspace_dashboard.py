import json
from decimal import Decimal
from pathlib import Path

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from catalog.models import Product, PurchaseInvoice, Supplier
from common.translations import DLUX_STRINGS as COMMON_STRINGS
from common.views import WorkspaceDashboardView
from finance.models import ExchangeRate
from sales.models import Delivery, Invoice, Payment
from sales.translations import DLUX_STRINGS as SALES_STRINGS

User = get_user_model()
rf = RequestFactory()
WORKSPACE_PREF_NAMESPACE = "switch_pos.workspace_dashboard.v1"


def _perm(code):
    app_label, codename = code.split(".", 1)
    return Permission.objects.get(content_type__app_label=app_label, codename=codename)


def _ctx(user):
    request = rf.get(reverse("common:workspace_dashboard"))
    request.user = user
    view = WorkspaceDashboardView()
    view.request, view.args, view.kwargs = request, (), {}
    return view.get_context_data()


def _tiles(ctx):
    return {tile["id"]: tile for tile in ctx["workspace_tiles"]}


def _attach_session(request):
    SessionMiddleware(lambda req: None).process_request(request)
    request.session.save()
    return request


class WorkspaceDashboardTests(TestCase):
    def setUp(self):
        ExchangeRate.objects.create(rate=Decimal("6.50"))

    def test_superuser_workspace_renders_dynamic_controls(self):
        user = User.objects.create_superuser("workspace_admin", "w@example.com", "x")
        supplier = Supplier.objects.create(name="Acme Supply")
        Product.objects.create(name="Lock X1", cost_usd=Decimal("20.00"), price_usd=Decimal("30.00"))
        PurchaseInvoice.objects.create(supplier=supplier, total_lyd=Decimal("650.00"))

        request = _attach_session(rf.get(reverse("common:workspace_dashboard")))
        request.user = user
        response = WorkspaceDashboardView.as_view()(request)
        response.render()
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn("data-workspace-dashboard", html)
        self.assertIn("data-dashboard-grid", html)
        self.assertIn("data-dashboard-customize", html)
        self.assertIn("common/css/workspace_dashboard.css?v=20260710d", html)
        self.assertIn("common/js/workspace_dashboard.js?v=20260713a", html)
        self.assertIn(WORKSPACE_PREF_NAMESPACE, html)
        self.assertIn('data-app-pref-url-template="/staff/sys/api/preferences/app/__namespace__/"', html)
        self.assertIn('data-widget-id="quick_actions"', html)
        self.assertIn('data-widget-id="purchase_month"', html)
        self.assertNotIn("data-dashboard-reset", html)

    def test_sales_rep_workspace_uses_owned_invoice_totals(self):
        rep = User.objects.create_user("rep", password="x")
        rep.user_permissions.add(_perm("sales.view_invoice"))
        other = User.objects.create_user("rep2", password="x")
        today = timezone.localdate()
        Invoice.objects.create(
            exchange_rate=Decimal("6.50"),
            invoice_date=today,
            status=Invoice.STATUS_ISSUED,
            total_lyd=Decimal("100.00"),
            created_by=rep,
            salesperson=rep,
        )
        Invoice.objects.create(
            exchange_rate=Decimal("6.50"),
            invoice_date=today,
            status=Invoice.STATUS_ISSUED,
            total_lyd=Decimal("500.00"),
            created_by=other,
            salesperson=other,
        )

        tiles = _tiles(_ctx(User.objects.get(pk=rep.pk)))

        self.assertEqual(tiles["sales_today"]["value"], "100.00")
        self.assertEqual(tiles["sales_month"]["value"], "100.00")
        self.assertNotIn("quick_actions", tiles)

    def test_payment_only_user_still_gets_payment_tile(self):
        cashier = User.objects.create_user("cashier", password="x")
        cashier.user_permissions.add(_perm("sales.view_payment"))
        rep = User.objects.create_user("rep", password="x")
        invoice = Invoice.objects.create(
            exchange_rate=Decimal("6.50"),
            status=Invoice.STATUS_ISSUED,
            total_lyd=Decimal("200.00"),
            created_by=rep,
            salesperson=rep,
        )
        Payment.objects.create(
            invoice=invoice,
            amount=Decimal("75.00"),
            paid_at=timezone.now(),
            created_by=cashier,
        )

        tiles = _tiles(_ctx(User.objects.get(pk=cashier.pk)))

        self.assertIn("cash_today", tiles)
        self.assertEqual(tiles["cash_today"]["value"], "75.00")
        self.assertNotIn("sales_today", tiles)

    def test_courier_workspace_uses_assigned_delivery_scope(self):
        courier = User.objects.create_user("courier", password="x")
        courier.user_permissions.add(_perm("sales.view_delivery"))
        other = User.objects.create_user("courier2", password="x")
        Delivery.objects.create(address="Mine", assigned_to=courier)
        Delivery.objects.create(address="Theirs", assigned_to=other)

        tiles = _tiles(_ctx(User.objects.get(pk=courier.pk)))

        self.assertEqual(tiles["deliveries"]["value"], "1")
        self.assertEqual(len(tiles["delivery_board"]["items"]), 1)
        self.assertEqual(tiles["delivery_board"]["items"][0]["label"], "Mine")

    def test_common_and_sales_translations_keep_english_arabic_key_parity(self):
        self.assertEqual(set(COMMON_STRINGS["en"]), set(COMMON_STRINGS["ar"]))
        self.assertEqual(set(SALES_STRINGS["en"]), set(SALES_STRINGS["ar"]))

    def test_workspace_sidebar_label_is_translated(self):
        from dlux.discovery import discover_sidebar_catalog

        en_catalog = discover_sidebar_catalog(lang_code="en")
        ar_catalog = discover_sidebar_catalog(lang_code="ar")

        en_entry = next(entry for entry in en_catalog if entry["id"] == "common:workspace_dashboard")
        ar_entry = next(entry for entry in ar_catalog if entry["id"] == "common:workspace_dashboard")

        self.assertEqual(en_entry["label"], "Workspace")
        self.assertEqual(ar_entry["label"], "مساحة العمل")

    def test_workspace_layout_uses_dlux_app_preference_namespace(self):
        from django.urls import NoReverseMatch
        from dlux.models import SystemSettings

        try:
            url = reverse("update_app_preference", kwargs={"namespace": WORKSPACE_PREF_NAMESPACE})
        except NoReverseMatch:
            self.skipTest("DjangoLux app-preference endpoint requires dlux 1.4.2+")

        settings = SystemSettings.load()
        settings.is_configured = True
        settings.save(update_fields=["is_configured"])
        user = User.objects.create_user("layout_user", password="x")

        client = Client()
        self.assertTrue(client.login(username="layout_user", password="x"))
        payload = {
            "order": ["cash_today", "sales_today"],
            "hidden": ["recent_invoices"],
            "sizes": {"cash_today": "l"},
        }
        response = client.post(
            url,
            data=json.dumps(payload),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        user.profile.refresh_from_db()
        self.assertEqual(user.profile.preferences["app"][WORKSPACE_PREF_NAMESPACE], payload)

    def test_workspace_tile_css_covers_aether_rich_theme(self):
        css_path = Path(__file__).resolve().parents[1] / "static" / "common" / "css" / "workspace_dashboard.css"
        css = css_path.read_text(encoding="utf-8")

        self.assertIn(":root.theme-aether .workspace-shell", css)
        self.assertIn(":root.theme-aether .workspace-tile", css)
        self.assertIn(":root.theme-aether .workspace-drawer", css)
        self.assertIn(":root.theme-aether .workspace-empty", css)
        self.assertIn(":root.theme-aether .tile-tool", css)
        self.assertIn(":root.theme-aether .action-chip", css)
        self.assertIn("--ws-green-rgb: 74, 222, 128;", css)
        self.assertIn("--tile-accent-rgb: var(--ws-green-rgb);", css)

    def test_workspace_js_uses_reversed_app_preference_url(self):
        js_path = Path(__file__).resolve().parents[1] / "static" / "common" / "js" / "workspace_dashboard.js"
        js = js_path.read_text(encoding="utf-8")

        self.assertIn("appPrefUrlTemplate", js)
        self.assertIn("localStorage.removeItem(storageKey)", js)
        self.assertIn("fetch(url", js)
        self.assertLess(js.index("const url = appPrefUrl();"), js.index("window.updateAppPreference"))
        self.assertNotIn("data-dashboard-reset", js)
