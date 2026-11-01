"""Attachments are served through ``common:stored_file`` with DjangoLux's
``serve_file``, behind the owning record's login, permission and ownership checks."""
import shutil
import tempfile
from decimal import Decimal
from pathlib import Path

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.base import ContentFile
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from catalog.models import PurchaseInvoice
from dlux.models import SystemSettings
from finance.models import Expense

PDF = b"%PDF-1.4\n" + b"0123456789" * 100


class StoredFileTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.media_root = tempfile.mkdtemp()
        cls.media = override_settings(MEDIA_ROOT=cls.media_root)
        cls.media.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls.media.disable()
        shutil.rmtree(cls.media_root, ignore_errors=True)

    def setUp(self):
        settings = SystemSettings.load()
        settings.is_configured = True
        settings.save(update_fields=["is_configured"])
        self.invoice = PurchaseInvoice.objects.create(supplier_name="Tripoli Imports", exchange_rate=Decimal("8.35"))
        self.invoice.attachment.save("supplier.pdf", ContentFile(PDF))
        self.invoice_url = reverse(
            "common:stored_file", args=["catalog", "purchaseinvoice", self.invoice.pk, "attachment"]
        )

    def _client(self, username, *codenames):
        user = get_user_model().objects.create_user(username, password="x", is_staff=True)
        for code in codenames:
            user.user_permissions.add(Permission.objects.get(codename=code))
        client = Client()
        client.force_login(user)
        return client, user

    def _expense(self, owner):
        expense = Expense.objects.create(amount_lyd=Decimal("120.00"), paid_by=owner, created_by=owner)
        expense.attachment.save("receipt.pdf", ContentFile(PDF))
        return expense, reverse("common:stored_file", args=["finance", "expense", expense.pk, "attachment"])

    def test_file_url_points_at_the_view(self):
        self.assertEqual(self.invoice.attachment.url, self.invoice_url)
        self.assertFalse(self.invoice.attachment.url.startswith("/media/"))

    def test_anonymous_is_sent_to_login(self):
        response = Client().get(self.invoice_url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response["Location"])

    def test_without_view_permission_is_refused(self):
        client, _ = self._client("clerk")
        self.assertEqual(client.get(self.invoice_url).status_code, 403)

    def test_with_view_permission_the_file_is_served_inline(self):
        client, _ = self._client("buyer", "view_purchaseinvoice")
        response = client.get(self.invoice_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), PDF)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertNotIn("attachment", response.get("Content-Disposition", ""))
        self.assertIn("private", response["Cache-Control"])

    def test_byte_ranges_are_answered(self):
        client, _ = self._client("buyer", "view_purchaseinvoice")
        response = client.get(self.invoice_url, HTTP_RANGE="bytes=0-7")
        self.assertEqual(response.status_code, 206)
        self.assertEqual(b"".join(response.streaming_content), PDF[:8])

    def test_unknown_field_or_model_is_not_reachable(self):
        client, _ = self._client("buyer", "view_purchaseinvoice", "view_product")
        for args in (
            ["catalog", "purchaseinvoice", self.invoice.pk, "notes"],
            ["catalog", "product", 1, "image"],
        ):
            with self.subTest(args=args):
                self.assertEqual(client.get(reverse("common:stored_file", args=args)).status_code, 404)

    def test_expense_receipt_follows_row_ownership(self):
        owner_client, owner = self._client("rep", "view_expense")
        other_client, _ = self._client("other_rep", "view_expense")
        manager_client, _ = self._client("manager", "view_expense", "view_all_expense")
        _, url = self._expense(owner)
        self.assertEqual(owner_client.get(url).status_code, 200)
        self.assertEqual(other_client.get(url).status_code, 404)
        self.assertEqual(manager_client.get(url).status_code, 200)

    def test_record_without_a_file_is_404(self):
        client, _ = self._client("buyer", "view_purchaseinvoice")
        empty = PurchaseInvoice.objects.create(supplier_name="No file", exchange_rate=Decimal("8.35"))
        url = reverse("common:stored_file", args=["catalog", "purchaseinvoice", empty.pk, "attachment"])
        self.assertEqual(client.get(url).status_code, 404)


class StoredFileProxyTests(SimpleTestCase):
    """Stack schema 4: the proxy asks DjangoLux before serving any private /media/ file."""

    def _caddyfile(self):
        return (Path(__file__).resolve().parents[2] / ".proxy" / "Caddyfile").read_text(encoding="utf-8")

    def test_proxy_asks_the_mounted_media_access_view(self):
        caddyfile = self._caddyfile()
        self.assertIn(f"uri {reverse('dlux_media_access')}", caddyfile)
        self.assertEqual(reverse("dlux_media_access"), "/staff/sys/files/media-access/")
        self.assertNotIn("handle_path /media/*", caddyfile)
        self.assertIn("respond /media/dlux_backups/* 404", caddyfile)

    def test_storefront_images_are_public_and_paperwork_app_only(self):
        from django.conf import settings

        self.assertEqual(
            settings.DLUX_PUBLIC_MEDIA, ["catalog/products/", "catalog/services/", "public_catalog/listings/"]
        )
        self.assertEqual(settings.DLUX_APP_ONLY_MEDIA, ["purchase_invoices/", "finance/expenses/"])


class MediaDecisionTests(TestCase):
    """What the proxy may serve straight from /media/ for this project's folders."""

    def _request(self, user=None):
        from django.contrib.auth.models import AnonymousUser
        from django.test import RequestFactory

        request = RequestFactory().get("/staff/sys/files/media-access/")
        request.user = user or AnonymousUser()
        return request

    def test_decisions(self):
        from dlux.files.media import media_decision

        staff = get_user_model().objects.create_user("viewer", password="x", is_staff=True)
        cases = (
            ("catalog/products/lock.jpg", True, True),
            ("public_catalog/listings/banner.png", True, True),
            ("purchase_invoices/supplier.pdf", False, False),
            ("Purchase_Invoices/supplier.pdf", False, False),
            ("finance/expenses/receipt.pdf", False, False),
            ("dlux_backups/system.dlb", False, False),
            ("exports/report.pdf", False, True),
        )
        for name, anonymous, signed_in in cases:
            with self.subTest(name=name):
                self.assertIs(media_decision(self._request(), name), anonymous)
                self.assertIs(media_decision(self._request(staff), name), signed_in)


class MediaAccessViewTests(TestCase):
    """The proxy's sub-request, through the whole middleware stack, at both URLs."""

    def setUp(self):
        settings = SystemSettings.load()
        settings.is_configured = True
        settings.save(update_fields=["is_configured"])

    def test_both_urls_decide_the_same(self):
        for url in ("/staff/sys/files/media-access/", "/sys/files/media-access/"):
            for uri, status in (
                ("/media/catalog/products/lock.jpg", 204),
                ("/media/purchase_invoices/supplier.pdf", 403),
                ("/media/finance/../purchase_invoices/supplier.pdf", 403),
                ("/media/exports/report.pdf", 403),
            ):
                with self.subTest(url=url, uri=uri):
                    response = Client().get(url, HTTP_X_FORWARDED_URI=uri)
                    self.assertEqual(response.status_code, status)
