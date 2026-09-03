"""Per-user Products layout switcher (table / grid / light)."""
import json
from decimal import Decimal
from pathlib import Path

from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse

from catalog.models import Product
from catalog.product_layouts import PRODUCTS_LAYOUT_NS, get_products_layout
from catalog.tables import ProductLightTable, ProductTable
from catalog.views import ProductListView

User = get_user_model()
rf = RequestFactory()


def _attach(request, user):
    SessionMiddleware(lambda req: None).process_request(request)
    request.session.save()
    request.user = user
    request._messages = FallbackStorage(request)
    return request


def _set_layout(user, value):
    Profile = apps.get_model("dlux", "Profile")
    profile, _ = Profile.all_objects.get_or_create(user=user)
    prefs = dict(profile.preferences or {})
    app = dict(prefs.get("app") or {})
    if value is None:
        app.pop(PRODUCTS_LAYOUT_NS, None)
    else:
        app[PRODUCTS_LAYOUT_NS] = value
    prefs["app"] = app
    profile.preferences = prefs
    profile.save()
    return User.objects.get(pk=user.pk)  # fresh instance so the relation reloads


def _set_global_default(value):
    """Set the shop-wide default via SystemSettings.extra_config['app'][ns]."""
    SystemSettings = apps.get_model("dlux", "SystemSettings")
    s = SystemSettings.load()
    extra = dict(s.extra_config or {})
    app = dict(extra.get("app") or {})
    if value is None:
        app.pop(PRODUCTS_LAYOUT_NS, None)
    else:
        app[PRODUCTS_LAYOUT_NS] = {"default_layout": value}
    extra["app"] = app
    s.extra_config = extra
    s.save()


class ProductsLayoutReaderTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser("layoutadmin", "l@example.com", "x")

    def _layout_for(self, user):
        req = _attach(rf.get("/catalog/"), user)
        return get_products_layout(req)

    def test_default_is_table(self):
        self.assertEqual(self._layout_for(self.user), "table")

    def test_reads_grid_and_light(self):
        self.assertEqual(self._layout_for(_set_layout(self.user, "grid")), "grid")
        self.assertEqual(self._layout_for(_set_layout(self.user, "light")), "light")

    def test_unknown_value_falls_back_to_table(self):
        self.assertEqual(self._layout_for(_set_layout(self.user, "bogus")), "table")


class ProductsLayoutGlobalDefaultTests(TestCase):
    """Effective layout resolves per-user override → global admin default → table."""

    def setUp(self):
        self.user = User.objects.create_superuser("gd", "g@example.com", "x")

    def tearDown(self):
        # SystemSettings.save() refreshes an external config cache that the test's
        # DB-transaction rollback does not undo — clear it so the global default
        # doesn't leak into later tests.
        _set_global_default(None)

    def _layout_for(self, user):
        return get_products_layout(_attach(rf.get("/catalog/"), user))

    def test_global_default_used_without_user_override(self):
        _set_global_default("grid")
        self.assertEqual(self._layout_for(self.user), "grid")

    def test_user_override_wins_over_global_default(self):
        _set_global_default("grid")
        user = _set_layout(self.user, "light")
        self.assertEqual(self._layout_for(user), "light")

    def test_unknown_global_default_falls_back_to_table(self):
        _set_global_default("bogus")
        self.assertEqual(self._layout_for(self.user), "table")

    def test_no_config_defaults_to_table(self):
        _set_global_default(None)
        self.assertEqual(self._layout_for(self.user), "table")


class ProductListViewLayoutTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser("listadmin", "a@example.com", "x")
        Product.objects.create(name="Widget", cost_usd=Decimal("2.00"), price_usd=Decimal("3.00"))

    def _render(self, user):
        req = _attach(rf.get(reverse("catalog:product_list")), user)
        resp = ProductListView.as_view()(req)
        resp.render()
        self.assertEqual(resp.status_code, 200)
        return resp

    def test_table_layout_default(self):
        resp = self._render(self.user)
        # Table and Light are the shared list page; only the columns differ.
        self.assertIn("common/scoped_list.html", resp.template_name)
        html = resp.content.decode()
        self.assertIn("data-products-layout-switch", html)  # toggle present
        self.assertIn('data-app-pref-url-template="/staff/sys/api/preferences/app/__namespace__/"', html)
        # `dlux_static` busts the cache from the asset's own mtime, replacing the
        # hand-bumped `?v=` the retired template carried.
        self.assertRegex(html, r"catalog/js/products_layout\.js\?v=[^\"']+")

    def test_light_layout_uses_light_table(self):
        user = _set_layout(self.user, "light")
        view = ProductListView()
        view.request = _attach(rf.get(reverse("catalog:product_list")), user)
        self.assertIs(view.get_table_class(), ProductLightTable)
        # sanity: default/grid keep the full table
        self.assertIs(ProductListView.table_class, ProductTable)
        resp = self._render(user)
        self.assertIn("common/scoped_list.html", resp.template_name)

    def test_grid_layout_renders_cards(self):
        user = _set_layout(self.user, "grid")
        resp = self._render(user)
        self.assertIn("catalog/product_grid.html", resp.template_name)
        html = resp.content.decode()
        self.assertIn("data-products-grid", html)
        self.assertIn("dlux-table-shell", html)          # reuses dlux surface
        self.assertIn("?action=view", html)              # expand → detail modal
        self.assertIn("data-products-layout-switch", html)  # toggle still present


class ProductsLayoutPreferenceEndpointTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("layout_writer", password="x")

    def test_staff_prefixed_endpoint_persists_products_layout(self):
        url = reverse("update_app_preference", kwargs={"namespace": PRODUCTS_LAYOUT_NS})
        self.assertEqual(url, "/staff/sys/api/preferences/app/switch_pos.products_layout/")

        client = Client()
        self.assertTrue(client.login(username="layout_writer", password="x"))
        response = client.post(url, data=json.dumps("light"), content_type="application/json")

        self.assertEqual(response.status_code, 200)
        Profile = apps.get_model("dlux", "Profile")
        profile = Profile.all_objects.get(user=self.user)
        self.assertEqual(profile.preferences["app"][PRODUCTS_LAYOUT_NS], "light")


class ProductsLayoutStaticContractTests(TestCase):
    def test_products_layout_js_uses_reversed_preference_url_before_reload(self):
        js_path = Path(__file__).resolve().parents[1] / "static" / "catalog" / "js" / "products_layout.js"
        js = js_path.read_text(encoding="utf-8")

        self.assertIn("data-app-pref-url-template", js)
        self.assertIn("fetch(url", js)
        self.assertIn("syncAppPrefCache(ns, value)", js)
        self.assertNotIn("/sys/api/preferences/app/", js)
        self.assertNotIn("then(reload, reload)", js)


def _import_options_or_skip(test):
    """The Options-card registry (dlux.options.register_card) ships in dlux >= 1.3.
    The dev/prod container runs dlux 1.4.x, but the host venv used for `manage.py
    test` may still be on 1.2.x — skip there so the suite stays green while the
    card is still exercised at runtime."""
    try:
        import dlux.options as options
    except ImportError:
        test.skipTest("dlux.options not available (host dlux < 1.3); card registers at runtime")
    return options


class ProductsLayoutOptionCardTests(TestCase):
    def setUp(self):
        self.super = User.objects.create_superuser("cardadmin", "c@example.com", "x")
        self.plain = User.objects.create_user("plain", password="x")

    def test_card_registered(self):
        options = _import_options_or_skip(self)
        # Importing the module triggers registration if autodiscovery hasn't run.
        import catalog.dlux_options  # noqa: F401
        self.assertIn("switch_pos.products_layout", options._REGISTRY)

    def test_card_visible_only_with_view_product(self):
        options = _import_options_or_skip(self)
        import catalog.dlux_options  # noqa: F401
        req_super = _attach(rf.get("/sys/options/"), self.super)
        ids = [c["id"] for c in options.get_visible_cards(req_super)]
        self.assertIn("switch_pos.products_layout", ids)

        req_plain = _attach(rf.get("/sys/options/"), self.plain)
        ids_plain = [c["id"] for c in options.get_visible_cards(req_plain)]
        self.assertNotIn("switch_pos.products_layout", ids_plain)

    def test_global_default_settings_tile_superuser_only(self):
        options = _import_options_or_skip(self)
        if not hasattr(options, "get_visible_app_settings"):
            self.skipTest("register_app_settings not available (dlux < 1.4.4)")
        import catalog.dlux_options  # noqa: F401

        req_super = _attach(rf.get("/sys/options/"), self.super)
        ns = [d["namespace"] for d in options.get_visible_app_settings(req_super)]
        self.assertIn("switch_pos.products_layout", ns)

        # Settings tiles are superuser-only — a plain user sees none of them.
        req_plain = _attach(rf.get("/sys/options/"), self.plain)
        ns_plain = [d["namespace"] for d in options.get_visible_app_settings(req_plain)]
        self.assertNotIn("switch_pos.products_layout", ns_plain)
