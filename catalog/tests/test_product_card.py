import json
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from catalog.models import Product, ProductVariant, StockMovement
from catalog.tables import ProductLightTable, ProductTable


User = get_user_model()


class ProductCardTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser("cardadmin", "card@example.com", "x")
        self.client.force_login(self.user)
        self.product = Product.objects.create(
            name="Brake Pad",
            barcode="BP-001",
            cost_usd=Decimal("12.00"),
            price_usd=Decimal("15.00"),
        )
        self.variant = ProductVariant.objects.create(
            product=self.product,
            color=Product.COLOR_BLACK,
            size="Front",
        )
        StockMovement.objects.create(
            product=self.product,
            variant=self.variant,
            movement_type=StockMovement.TYPE_IN,
            quantity=Decimal("6"),
            reference="OPENING",
            reason="Opening balance",
        )

    def test_card_is_a_dynamic_modal_payload_with_stock_and_history(self):
        response = self.client.get(reverse("catalog:product_card", args=[self.product.pk]))

        self.assertEqual(response.status_code, 200)
        html = response.json()["html"]
        self.assertIn("Brake Pad", html)
        self.assertIn("BP-001", html)
        self.assertIn("Front", html)
        self.assertIn("OPENING", html)
        self.assertIn("15.00 USD", html)

    def test_full_and_light_tables_open_the_item_card_on_double_click(self):
        expected = reverse("catalog:product_card", args=[self.product.pk])
        for table_class in (ProductTable, ProductLightTable):
            table = table_class([self.product])
            actions = json.loads(table.row_attrs["data-dlux-actions"](self.product))
            card = next(action for action in actions if (action.get("data") or {}).get("url") == expected)
            self.assertTrue(card["dblclick"])

    def test_card_requires_view_permission(self):
        self.client.logout()
        plain = User.objects.create_user("plain-card", password="x", is_staff=True)
        self.client.force_login(plain)

        response = self.client.get(reverse("catalog:product_card", args=[self.product.pk]))

        self.assertEqual(response.status_code, 403)
