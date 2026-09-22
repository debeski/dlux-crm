import json
import re
import tempfile
from decimal import Decimal
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import translation

from catalog.forms import PurchaseInvoiceLineForm, StockMovementForm
from catalog.models import Product, ProductVariant, PurchaseInvoice, StockMovement, Supplier
from catalog.views import (
    OpeningStockDetailView,
    OpeningStockEditorView,
    OpeningStockImportFinalizeView,
    OpeningStockImportPreviewView,
    PurchaseInvoiceCreateView,
    StockMovementListView,
)
from finance.models import ExchangeRate
from sales.forms import InvoiceItemForm

User = get_user_model()
rf = RequestFactory()


def _attach_request_state(request, user):
    SessionMiddleware(lambda req: None).process_request(request)
    request.session.save()
    request.user = user
    request._messages = FallbackStorage(request)
    return request


class PurchaseInvoiceTests(TestCase):
    def setUp(self):
        ExchangeRate.objects.create(rate=Decimal("6.50"))
        self.user = User.objects.create_superuser("stockadmin", "s@example.com", "x")

    def _row(self, **over):
        base = {
            "product": "",
            "name": "",
            "unit": Product.UNIT_PIECE,
            "barcode": "",
            "cost_usd": "0.00",
            "markup_percent": "0.00",
            "price_usd": "0.00",
            "price_lyd_override": "",
            "color": "",
            "size": "",
            "quantity": "0.00",
        }
        base.update(over)
        return base

    def _post_data(self, rows, **header):
        data = {
            "supplier": "",
            "supplier_name": "Acme Supply",
            "supplier_phone": "0911111111",
            "supplier_address": "Tripoli",
            "invoice_date": "2026-07-09",
            "notes": "",
            "form-TOTAL_FORMS": str(len(rows)),
            "form-INITIAL_FORMS": "0",
            "form-MIN_NUM_FORMS": "0",
            "form-MAX_NUM_FORMS": "1000",
        }
        data.update(header)
        for i, row in enumerate(rows):
            for key, value in row.items():
                data[f"form-{i}-{key}"] = value
        return data

    def _post(self, data):
        req = _attach_request_state(
            rf.post(reverse("catalog:purchase_invoice_create"), data),
            self.user,
        )
        return PurchaseInvoiceCreateView.as_view()(req)

    def _get_create(self):
        req = _attach_request_state(
            rf.get(reverse("catalog:purchase_invoice_create")),
            self.user,
        )
        return PurchaseInvoiceCreateView.as_view()(req)

    def test_create_page_gives_the_line_totals_an_unlocalized_rate(self):
        # Arabic renders 6.50 as "6,50", which parseFloat reads as 6.
        with translation.override("ar"):
            content = self._get_create().content.decode()
        self.assertRegex(content, r'parseFloat\("6\.50*"\)')

    def test_quantity_inputs_step_by_one_and_accept_fractions(self):
        for form in (PurchaseInvoiceLineForm(), StockMovementForm(), InvoiceItemForm()):
            self.assertEqual(form.fields["quantity"].widget.attrs["step"], "any", type(form).__name__)

    def test_purchase_invoice_creates_supplier_product_line_and_stock_movement(self):
        data = self._post_data([
            self._row(
                name="Smart Lock",
                barcode="6290000000999",
                cost_usd="40.00",
                markup_percent="25.00",
                price_usd="50.00",
                color=Product.COLOR_BLUE,
                size="120x80x30 mm",
                quantity="5",
            )
        ])
        resp = self._post(data)

        invoice = PurchaseInvoice.objects.get()
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], reverse("catalog:purchase_invoice_detail", args=[invoice.pk]))
        self.assertEqual(invoice.number, "PINV-000001")
        self.assertEqual(invoice.total_usd, Decimal("200.00"))
        self.assertEqual(invoice.total_lyd, Decimal("1300.00"))

        supplier = Supplier.objects.get(name="Acme Supply")
        self.assertEqual((supplier.phone, supplier.address), ("0911111111", "Tripoli"))
        product = Product.objects.get(name="Smart Lock")
        self.assertEqual(product.stock_qty, Decimal("5.00"))
        self.assertEqual(product.cost_usd, Decimal("40.00"))
        self.assertEqual(product.price_usd, Decimal("50.00"))
        self.assertEqual(product.color, Product.COLOR_BLUE)
        self.assertEqual(product.size, "120x80x30 mm")
        variant = ProductVariant.objects.get(product=product, color=Product.COLOR_BLUE, size="120x80x30 mm")
        self.assertEqual(variant.stock_qty, Decimal("5.00"))

        line = invoice.lines.get()
        self.assertEqual(line.product_id, product.pk)
        self.assertEqual(line.variant_id, variant.pk)
        self.assertEqual(line.quantity, Decimal("5.00"))
        self.assertEqual(line.color, Product.COLOR_BLUE)
        self.assertEqual(line.size, "120x80x30 mm")
        movement = StockMovement.objects.get(product=product)
        self.assertEqual(movement.variant_id, variant.pk)
        self.assertEqual(movement.reference, invoice.number)
        self.assertEqual(movement.purchase_invoice_id, invoice.pk)
        self.assertEqual(movement.movement_type, StockMovement.TYPE_IN)

    def test_same_product_purchase_lines_keep_distinct_color_size_stock(self):
        product = Product.objects.create(name="Spare Key", cost_usd=Decimal("4.00"), price_usd=Decimal("6.00"))
        data = self._post_data([
            self._row(product=str(product.pk), name="Spare Key", color=Product.COLOR_ORANGE, size="13.56 MHz", cost_usd="4.00", price_usd="6.00", quantity="2"),
            self._row(product=str(product.pk), name="Spare Key", color=Product.COLOR_BLUE, size="13.56 MHz", cost_usd="4.00", price_usd="6.00", quantity="3"),
        ])
        self._post(data)

        product.refresh_from_db()
        orange = ProductVariant.objects.get(product=product, color=Product.COLOR_ORANGE, size="13.56 MHz")
        blue = ProductVariant.objects.get(product=product, color=Product.COLOR_BLUE, size="13.56 MHz")

        self.assertEqual(product.stock_qty, Decimal("5.00"))
        self.assertEqual(orange.stock_qty, Decimal("2.00"))
        self.assertEqual(blue.stock_qty, Decimal("3.00"))
        self.assertEqual(
            set(product.purchase_invoice_lines.values_list("color", "quantity")),
            {(Product.COLOR_ORANGE, Decimal("2.00")), (Product.COLOR_BLUE, Decimal("3.00"))},
        )
        self.assertEqual(
            set(product.movements.values_list("variant__color", "quantity")),
            {(Product.COLOR_ORANGE, Decimal("2.00")), (Product.COLOR_BLUE, Decimal("3.00"))},
        )

    def test_existing_product_is_reused_and_repriced(self):
        existing = Product.objects.create(name="Existing", cost_usd=Decimal("10.00"), price_usd=Decimal("12.00"))
        Product.objects.filter(pk=existing.pk).update(stock_qty=Decimal("2.00"))

        data = self._post_data([
            self._row(product=str(existing.pk), name="Existing", cost_usd="15.00", price_usd="20.00", quantity="3")
        ])
        self._post(data)

        existing.refresh_from_db()
        self.assertEqual(Product.objects.filter(name__iexact="Existing").count(), 1)
        self.assertEqual(existing.stock_qty, Decimal("5.00"))
        self.assertEqual(existing.cost_usd, Decimal("15.00"))
        self.assertEqual(existing.price_usd, Decimal("20.00"))

    def test_attachment_widget_belongs_to_purchase_invoice_not_sales_invoice(self):
        from catalog.forms import PurchaseInvoiceForm
        from sales.forms import InvoiceForm

        pform = PurchaseInvoiceForm()
        self.assertEqual(pform.fields["attachment"].widget.template_name, "dlux/forms/file_input.html")
        self.assertTrue(pform.is_multipart())

        sform = InvoiceForm(user=None)
        self.assertNotIn("attachment", sform.fields)
        self.assertFalse(sform.is_multipart())

    def test_purchase_invoice_accepts_pdf_attachment(self):
        with override_settings(MEDIA_ROOT=tempfile.mkdtemp()):
            data = self._post_data([
                self._row(name="With Attachment", cost_usd="10.00", price_usd="12.00", quantity="1")
            ])
            upload = SimpleUploadedFile("supplier.pdf", b"%PDF-1.4 x", content_type="application/pdf")
            resp = self._post({**data, "attachment": upload})
            invoice = PurchaseInvoice.objects.get()
            self.assertEqual(resp.status_code, 302)
            self.assertEqual(resp["Location"], reverse("catalog:purchase_invoice_detail", args=[invoice.pk]))
            self.assertTrue(invoice.attachment.name.startswith("purchase_invoices/"))

    def test_product_map_includes_purchase_autofill_fields(self):
        existing = Product.objects.create(
            name="Mapped",
            unit=Product.UNIT_BOX,
            barcode="6290000000012",
            cost_usd=Decimal("42.00"),
            markup_percent=Decimal("30.00"),
            price_usd=Decimal("54.60"),
            price_lyd_override=Decimal("410.00"),
            color=Product.COLOR_GOLD,
            size="Large / 30x20x10 cm",
        )
        ProductVariant.objects.create(
            product=existing,
            color=Product.COLOR_GOLD,
            size="Large / 30x20x10 cm",
            stock_qty=Decimal("6.00"),
        )

        resp = self._get_create()
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        match = re.search(r'<script id="product-map" type="application/json">(.*?)</script>', html)
        self.assertIsNotNone(match)
        payload = json.loads(match.group(1))
        row = payload[str(existing.pk)]

        self.assertEqual(row["cost"], 42.0)
        self.assertEqual(row["markup"], 30.0)
        self.assertEqual(row["price_usd"], 54.6)
        self.assertEqual(row["price_lyd"], 410.0)
        self.assertEqual(row["barcode"], "6290000000012")
        self.assertEqual(row["unit"], Product.UNIT_BOX)
        self.assertEqual(row["color"], Product.COLOR_GOLD)
        self.assertEqual(row["size"], "Large / 30x20x10 cm")
        self.assertEqual(row["variants"][0]["color"], Product.COLOR_GOLD)
        self.assertEqual(row["variants"][0]["stock_qty"], 6.0)

    def test_purchase_invoice_create_starts_with_one_empty_row(self):
        resp = self._get_create()
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()

        self.assertIn('name="form-TOTAL_FORMS" value="1"', html)

    def test_purchase_invoice_context_menu_prints_in_new_tab(self):
        from catalog.tables import PurchaseInvoiceTable

        invoice = PurchaseInvoice.objects.create(supplier_name="Acme")
        table = PurchaseInvoiceTable([invoice])
        actions = json.loads(table.row_attrs["data-dlux-actions"](invoice))
        print_action = next(
            action for action in actions
            if action.get("url") == reverse("catalog:purchase_invoice_print", args=[invoice.pk])
        )

        self.assertEqual(actions[0]["url"], reverse("catalog:purchase_invoice_detail", args=[invoice.pk]))
        self.assertTrue(actions[0]["dblclick"])
        self.assertEqual(print_action["target"], "_blank")


class OpeningStockOneTimeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser("openingadmin", "o@example.com", "x")
        self.product = Product.objects.create(name="Seed", cost_usd=Decimal("1.00"), price_usd=Decimal("2.00"))
        StockMovement.objects.create(
            product=self.product,
            movement_type=StockMovement.TYPE_IN,
            quantity=Decimal("1.00"),
            reason="Opening balance",
            reference="OPENING",
        )

    def test_opening_stock_editor_redirects_to_read_only_record_after_use(self):
        req = _attach_request_state(rf.get(reverse("catalog:opening_stock")), self.user)
        resp = OpeningStockEditorView.as_view()(req)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], reverse("catalog:opening_stock_detail"))

        detail_req = _attach_request_state(rf.get(reverse("catalog:opening_stock_detail")), self.user)
        detail = OpeningStockDetailView.as_view()(detail_req)
        detail.render()
        self.assertEqual(detail.status_code, 200)
        self.assertIn("Seed", detail.content.decode())
        self.assertIn("OPENING", detail.content.decode())

    def test_stock_movement_actions_switch_to_view_opening_stock(self):
        req = _attach_request_state(rf.get(reverse("catalog:stock_movement_list")), self.user)
        resp = StockMovementListView.as_view()(req)
        resp.render()
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn(reverse("catalog:opening_stock_detail"), html)
        self.assertIn(reverse("catalog:purchase_invoice_create"), html)


class OpeningStockExcelImportTests(TestCase):
    HEADERS = [
        "Name", "Category", "Unit", "Barcode", "Color", "Size / Spec",
        "Cost (USD)", "Markup %", "Price (USD)", "Manual LYD Price",
        "Quantity in Storage",
    ]

    def setUp(self):
        self.user = User.objects.create_superuser("exceladmin", "excel@example.com", "x")

    def workbook(self, rows):
        from openpyxl import Workbook

        workbook = Workbook()
        sheet = workbook.active
        sheet.append(self.HEADERS)
        for row in rows:
            sheet.append(row)
        output = BytesIO()
        workbook.save(output)
        return SimpleUploadedFile(
            "opening-stock.xlsx",
            output.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    def preview(self, rows):
        request = _attach_request_state(
            rf.post(
                reverse("catalog:opening_stock_import_preview"),
                {"file": self.workbook(rows)},
            ),
            self.user,
        )
        response = OpeningStockImportPreviewView.as_view()(request)
        return response, json.loads(response.content)

    def test_editor_exposes_the_excel_modal_and_required_headers(self):
        request = _attach_request_state(
            rf.get(reverse("catalog:opening_stock")), self.user
        )
        response = OpeningStockEditorView.as_view()(request)
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn("opening-stock-import-modal", html)
        self.assertIn("Quantity in Storage", html)
        self.assertIn(reverse("catalog:opening_stock_import_preview"), html)

    def test_preview_then_finalize_creates_products_variants_and_stock(self):
        response, payload = self.preview([[
            "Brake Pad", "", "pair", "BP-001", "black", "Front",
            12, 25, 15, "", 6,
        ]])

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["can_finalize"])
        self.assertEqual(payload["summary"], {"total": 1, "create": 1, "update": 0, "conflicts": 0})
        self.assertEqual(Product.objects.count(), 0)

        request = _attach_request_state(
            rf.post(
                reverse("catalog:opening_stock_import_finalize"),
                {"token": payload["token"]},
            ),
            self.user,
        )
        finalized = OpeningStockImportFinalizeView.as_view()(request)

        self.assertEqual(finalized.status_code, 200)
        product = Product.objects.get(name="Brake Pad")
        self.assertEqual(product.stock_qty, Decimal("6.00"))
        self.assertEqual(product.cost_usd, Decimal("12.00"))
        variant = ProductVariant.objects.get(product=product)
        self.assertEqual((variant.color, variant.size, variant.stock_qty), ("black", "Front", Decimal("6.00")))
        self.assertTrue(StockMovement.objects.filter(product=product, reference="OPENING").exists())

    def test_unknown_category_is_a_blocking_conflict(self):
        response, payload = self.preview([[
            "Brake Pad", "Unknown Category", "pair", "BP-001", "", "Front",
            12, 25, 15, "", 6,
        ]])

        self.assertEqual(response.status_code, 200)
        self.assertFalse(payload["can_finalize"])
        self.assertEqual(payload["summary"]["conflicts"], 1)
        self.assertIn("does not exist", payload["rows"][0]["errors"][0])

    def test_existing_product_preview_reports_an_update_without_writing(self):
        product = Product.objects.create(
            name="Brake Pad", barcode="BP-001", unit=Product.UNIT_PAIR,
            cost_usd=Decimal("10.00"), price_usd=Decimal("13.00"),
        )
        response, payload = self.preview([[
            "Brake Pad", "", "pair", "BP-001", "", "Front",
            12, 25, 15, "", 2,
        ]])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["summary"]["update"], 1)
        self.assertIn("Cost (USD)", payload["rows"][0]["changes"])
        product.refresh_from_db()
        self.assertEqual(product.cost_usd, Decimal("10.00"))
