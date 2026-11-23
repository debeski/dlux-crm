"""Cost stays with those who edit products; a stock take moves the variant
bucket; the Add Stock button appears only for users the form lets in."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import RequestFactory, TestCase
from django.urls import reverse

from catalog.models import Product, ProductVariant, StockMovement, StockTake, StockTakeLine
from catalog.views import PurchaseInvoiceListView, StockMovementListView

User = get_user_model()
rf = RequestFactory()


def _perm(code):
    app_label, codename = code.split(".", 1)
    return Permission.objects.get(content_type__app_label=app_label, codename=codename)


def _user(name, *perms):
    user = User.objects.create_user(name, password="x")
    user.user_permissions.add(*(_perm(code) for code in perms))
    return User.objects.get(pk=user.pk)


class ProductCardCostTests(TestCase):
    def setUp(self):
        from dlux.models import SystemSettings

        settings = SystemSettings.load()
        settings.is_configured = True
        settings.save(update_fields=["is_configured"])
        self.product = Product.objects.create(
            name="Brake Pad", cost_usd=Decimal("12.34"), markup_percent=Decimal("21.50"), price_usd=Decimal("15.00"),
        )

    def _card(self, user):
        self.client.force_login(user)
        response = self.client.get(reverse("catalog:product_card", args=[self.product.pk]))
        self.assertEqual(response.status_code, 200)
        return response.json()["html"]

    def test_a_viewer_does_not_see_cost_or_markup(self):
        html = self._card(_user("rep", "catalog.view_product"))
        self.assertIn("15.00", html)
        self.assertNotIn("12.34", html)
        self.assertNotIn("21.50", html)

    def test_a_product_editor_sees_cost_and_markup(self):
        html = self._card(_user("manager", "catalog.view_product", "catalog.change_product"))
        self.assertIn("12.34", html)
        self.assertIn("21.50", html)

    def test_the_record_view_on_either_modal_route_is_the_item_card(self):
        rep = _user("rep", "catalog.view_product")
        self.client.force_login(rep)
        for url in (
            reverse("scoped_modal_manager", args=["catalog", "product", self.product.pk]),
            reverse("modal_manager", args=["catalog", "product", self.product.pk]),
        ):
            with self.subTest(url=url):
                response = self.client.get(url, {"action": "view"})
                self.assertEqual(response.status_code, 200)
                html = response.json()["html"]
                self.assertIn("Brake Pad", html)
                self.assertNotIn("12.34", html)
                self.assertNotIn("21.50", html)


class StockTakeBucketTests(TestCase):
    """A take counts every colour/size bucket on its own line."""

    def _stock(self, product, variant, quantity):
        StockMovement.objects.create(product=product, variant=variant, movement_type=StockMovement.TYPE_IN, quantity=Decimal(quantity))

    def _take(self, counts):
        """Create a take through the count sheet with ``{input_name: counted}``."""
        from django.contrib.messages.storage.fallback import FallbackStorage

        from catalog.views import StockTakeCreateView

        request = rf.post("/", {**counts, "notes": ""})
        request.user = User.objects.create_superuser("counter", "c@example.com", "x")
        request.session = {}
        request._messages = FallbackStorage(request)
        StockTakeCreateView.as_view()(request)
        take = StockTake.objects.latest("pk")
        take.apply()
        return take

    def test_each_bucket_is_counted_and_adjusted_on_its_own(self):
        product = Product.objects.create(name="Lock", cost_usd=Decimal("1"))
        black = ProductVariant.objects.create(product=product, color=Product.COLOR_BLACK)
        gold = ProductVariant.objects.create(product=product, color=Product.COLOR_GOLD)
        self._stock(product, black, "4")
        self._stock(product, gold, "6")

        take = self._take({
            StockTakeLine.input_name(product, black): "3",
            StockTakeLine.input_name(product, gold): "6",
        })

        self.assertEqual(
            sorted((line.variant_id, line.system_qty) for line in take.lines.all()),
            sorted([(black.pk, Decimal("4")), (gold.pk, Decimal("6"))]),
        )
        movement = StockMovement.objects.get(reference=take.number)
        self.assertEqual((movement.variant, movement.quantity), (black, Decimal("-1")))
        for bucket, expected in ((black, "3"), (gold, "6")):
            bucket.refresh_from_db()
            self.assertEqual(bucket.stock_qty, Decimal(expected))
        product.refresh_from_db()
        self.assertEqual(product.stock_qty, Decimal("9"))

    def test_stock_outside_the_buckets_gets_its_own_line(self):
        product = Product.objects.create(name="Fob", cost_usd=Decimal("1"))
        bucket = ProductVariant.objects.create(product=product, color=Product.COLOR_BLACK)
        self._stock(product, bucket, "5")
        self._stock(product, None, "2")  # a movement recorded without a bucket

        take = self._take({
            StockTakeLine.input_name(product, bucket): "5",
            StockTakeLine.input_name(product, None): "0",
        })

        outside = take.lines.get(variant__isnull=True)
        self.assertEqual(outside.system_qty, Decimal("2"))
        product.refresh_from_db()
        bucket.refresh_from_db()
        self.assertEqual((product.stock_qty, bucket.stock_qty), (Decimal("5"), Decimal("5")))

    def test_a_product_without_buckets_keeps_one_line(self):
        product = Product.objects.create(name="Cable", cost_usd=Decimal("1"))
        self._stock(product, None, "10")
        take = self._take({StockTakeLine.input_name(product, None): "7"})
        self.assertEqual(take.lines.count(), 1)
        product.refresh_from_db()
        self.assertEqual(product.stock_qty, Decimal("7"))


class AddStockButtonTests(TestCase):
    INTAKE = ("catalog.add_purchaseinvoice", "catalog.add_product", "catalog.add_stockmovement")

    def _urls(self, view_class, user):
        view = view_class()
        view.request = rf.get("/")
        view.request.user = user
        view.kwargs = {}
        return {action.get("url") for action in view.get_ribbon_action_specs()}

    def test_the_button_needs_every_permission_the_form_needs(self):
        target = reverse("catalog:purchase_invoice_create")
        without = _user("intake", *self.INTAKE, "catalog.view_stockmovement", "catalog.view_purchaseinvoice")
        with_change = _user("intake_full", *self.INTAKE, "catalog.change_product", "catalog.view_stockmovement", "catalog.view_purchaseinvoice")
        for view_class in (StockMovementListView, PurchaseInvoiceListView):
            with self.subTest(view=view_class.__name__):
                self.assertNotIn(target, self._urls(view_class, without))
                self.assertIn(target, self._urls(view_class, with_change))
