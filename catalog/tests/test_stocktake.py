"""
Stock take (physical inventory count) → Adjustment movements, and the inventory
valuation report.
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core.exceptions import ValidationError
from django.test import RequestFactory, TestCase
from django.urls import reverse

from catalog.models import Product, StockMovement, StockTake, StockTakeLine
from catalog.views import InventoryValuationView, StockTakeCreateView
from finance.models import ExchangeRate

User = get_user_model()
rf = RequestFactory()


def _perm(code):
    app_label, codename = code.split(".", 1)
    return Permission.objects.get(content_type__app_label=app_label, codename=codename)


def _product(name, stock, cost="1.00", track=True):
    p = Product.objects.create(name=name, cost_usd=Decimal(cost), track_stock=track)
    Product.objects.filter(pk=p.pk).update(stock_qty=Decimal(stock))
    p.refresh_from_db()
    return p


class StockTakeModelTests(TestCase):
    def test_auto_number(self):
        t = StockTake.objects.create()
        self.assertEqual(t.number, f"ST-{t.pk:06d}")

    def test_line_variance(self):
        p = _product("A", "10")
        t = StockTake.objects.create()
        ln = StockTakeLine.objects.create(stock_take=t, product=p, system_qty=Decimal("10"), counted_qty=Decimal("8"))
        self.assertEqual(ln.variance, Decimal("-2"))
        uncounted = StockTakeLine.objects.create(stock_take=t, product=_product("B", "3"), system_qty=Decimal("3"))
        self.assertIsNone(uncounted.variance)

    def test_apply_posts_adjustments_and_sets_stock(self):
        short = _product("Short", "10")     # counted 8 → -2
        over = _product("Over", "5")        # counted 7 → +2
        exact = _product("Exact", "4")      # counted 4 → no adjustment
        untracked = _product("Svc", "0", track=False)
        t = StockTake.objects.create()
        StockTakeLine.objects.create(stock_take=t, product=short, system_qty=Decimal("10"), counted_qty=Decimal("8"))
        StockTakeLine.objects.create(stock_take=t, product=over, system_qty=Decimal("5"), counted_qty=Decimal("7"))
        StockTakeLine.objects.create(stock_take=t, product=exact, system_qty=Decimal("4"), counted_qty=Decimal("4"))
        StockTakeLine.objects.create(stock_take=t, product=untracked, system_qty=Decimal("0"), counted_qty=Decimal("9"))

        t.apply()

        short.refresh_from_db(); over.refresh_from_db(); exact.refresh_from_db(); untracked.refresh_from_db()
        self.assertEqual(short.stock_qty, Decimal("8.00"))   # adjusted down
        self.assertEqual(over.stock_qty, Decimal("7.00"))    # adjusted up
        self.assertEqual(exact.stock_qty, Decimal("4.00"))   # untouched
        self.assertEqual(untracked.stock_qty, Decimal("0.00"))  # track_stock off → skipped
        # One adjustment per real discrepancy on a tracked product (short, over).
        adj = StockMovement.objects.filter(movement_type=StockMovement.TYPE_ADJUST, reference=t.number)
        self.assertEqual(adj.count(), 2)
        t.refresh_from_db()
        self.assertEqual(t.status, StockTake.STATUS_APPLIED)
        self.assertIsNotNone(t.applied_at)

    def test_apply_twice_raises(self):
        t = StockTake.objects.create()
        t.apply()
        with self.assertRaises(ValidationError):
            t.apply()

    def test_variance_value(self):
        ExchangeRate.objects.create(rate=Decimal("5.00"))
        p = _product("A", "10", cost="2.00")
        t = StockTake.objects.create()
        ln = StockTakeLine.objects.create(stock_take=t, product=p, system_qty=Decimal("10"), counted_qty=Decimal("8"))
        # variance -2 × cost 2 USD = -4 USD × rate 5 = -20 LYD
        self.assertEqual(ln.variance_value_lyd(Decimal("5.00")), Decimal("-20.00"))


class StockTakeViewTests(TestCase):
    def setUp(self):
        self.mgr = User.objects.create_user("mgr", password="x")
        for c in ("catalog.add_stocktake", "catalog.view_stocktake", "catalog.view_inventory_valuation"):
            self.mgr.user_permissions.add(_perm(c))
        self.mgr = User.objects.get(pk=self.mgr.pk)
        self.a = _product("A", "10", cost="2.00")
        self.b = _product("B", "5", cost="1.00")

    def _post(self, view, data):
        req = rf.post("/catalog/stock-takes/new/", data)
        req.user = self.mgr
        req.session = {}
        req._messages = FallbackStorage(req)
        return view.as_view()(req)

    def test_create_snapshots_and_builds_lines(self):
        resp = self._post(StockTakeCreateView, {f"count_{self.a.pk}": "8", f"count_{self.b.pk}": "", "notes": "Q1"})
        self.assertEqual(resp.status_code, 302)
        take = StockTake.objects.get()
        self.assertEqual(take.lines.count(), 2)  # all active tracked products snapshotted
        line_a = take.lines.get(product=self.a)
        self.assertEqual((line_a.system_qty, line_a.counted_qty), (Decimal("10.00"), Decimal("8.00")))
        line_b = take.lines.get(product=self.b)
        self.assertIsNone(line_b.counted_qty)  # blank → not counted

    def test_valuation_totals(self):
        ExchangeRate.objects.create(rate=Decimal("5.00"))
        req = rf.get("/catalog/valuation/")
        req.user = self.mgr
        view = InventoryValuationView()
        view.request, view.args, view.kwargs = req, (), {}
        ctx = view.get_context_data()
        # A: 10×2=20 USD, B: 5×1=5 USD → 25 USD × 5 = 125 LYD
        self.assertEqual(ctx["total_usd"], Decimal("25.00"))
        self.assertEqual(ctx["total_lyd"], Decimal("125.00"))
        self.assertEqual(ctx["item_count"], 2)

    def test_valuation_expected_profit(self):
        ExchangeRate.objects.create(rate=Decimal("5.00"))
        Product.objects.filter(pk=self.a.pk).update(price_lyd_override=Decimal("15.00"))
        Product.objects.filter(pk=self.b.pk).update(price_usd=Decimal("1.60"))
        req = rf.get("/catalog/valuation/")
        req.user = self.mgr
        view = InventoryValuationView()
        view.request, view.args, view.kwargs = req, (), {}
        ctx = view.get_context_data()
        a, b = ctx["rows"]
        # A: 10 × 15 LYD override = 150 − 100 cost = 50; B: 5 × (1.60 USD × 5) = 40 − 25 cost = 15
        self.assertEqual((a["sale_lyd"], a["profit_lyd"]), (Decimal("150.00"), Decimal("50.00")))
        self.assertEqual((b["sale_lyd"], b["profit_lyd"]), (Decimal("40.00"), Decimal("15.00")))
        self.assertEqual(ctx["total_sale_lyd"], Decimal("190.00"))
        self.assertEqual(ctx["total_profit_lyd"], Decimal("65.00"))
        self.assertEqual(ctx["margin_percent"], Decimal("34.21"))

    def test_valuation_page_renders_profit_figures(self):
        ExchangeRate.objects.create(rate=Decimal("5.00"))
        Product.objects.filter(pk=self.a.pk).update(price_lyd_override=Decimal("15.00"))
        req = rf.get("/catalog/valuation/")
        req.user = self.mgr
        req.session = {}
        req._messages = FallbackStorage(req)
        resp = InventoryValuationView.as_view()(req)
        content = resp.render().content.decode()
        # Sale 150 + 25 = 175 LYD against 125 cost → 50 profit, 28.57% margin.
        self.assertRegex(content, r"175[.,٫]00")
        self.assertRegex(content, r"28[.,٫]57%")
