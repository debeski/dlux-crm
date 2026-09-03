import json
from decimal import Decimal
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe
from django.utils.translation import gettext as _
from django.views import View
from django.views.generic import DetailView, TemplateView

from dlux.translations import get_current_language_code, get_strings
from dlux.utils import log_user_action

from common.access import apply_ownership, user_can_view_all
from common.editors import DocumentEditorView, sync_party
from common.views import RibbonPageMixin, ScopedListView, scope_filtered_queryset
from finance.models import CashDeposit, ExchangeRate
from finance.services import (
    get_cbl_official_rate,
    get_current_rate,
    get_ean_black_market_rate,
    has_configured_rate,
    quantize_lyd,
)

from .filters import CustomerFilter, DeliveryFilter, InvoiceFilter, PaymentFilter
from .forms import CustomerForm, InvoiceForm, InvoiceItemFormSet, PaymentForm
from .models import Customer, Delivery, Invoice, Payment
from .reports import (
    available_fiscal_years,
    build_financial_report,
    build_sales_report,
    build_sales_report_xlsx,
    fiscal_year_window,
    parse_window,
)
from .services import cancel_invoice, issue_invoice
from .tables import CustomerTable, DeliveryTable, InvoiceTable, PaymentTable


def _visible_invoices(user):
    """Invoices this user is allowed to see/act on (own + assigned, or all for a
    manager holding ``view_all_invoice``). The single ownership choke point for
    the full-page invoice flows that bypass ScopedListView."""
    return apply_ownership(Invoice.objects.all(), user)


def _visible_payments(user):
    """Payments this user may open on standalone payment surfaces."""
    return apply_ownership(
        Payment.objects.select_related("invoice", "invoice__customer", "created_by", "deposit"),
        user,
    )


# --------------------------------------------------------------------------- #
# Simple list pages
# --------------------------------------------------------------------------- #
class CustomerListView(ScopedListView):
    model = Customer
    permission_required = "sales.view_customer"
    table_class = CustomerTable
    filterset_class = CustomerFilter
    page_title_key = "page_customers"
    page_subtitle_key = "page_customers_sub"


class DeliveryListView(ScopedListView):
    model = Delivery
    permission_required = "sales.view_delivery"
    table_class = DeliveryTable
    filterset_class = DeliveryFilter
    page_title_key = "page_deliveries"
    page_subtitle_key = "page_deliveries_sub"


class PaymentListView(ScopedListView):
    model = Payment
    permission_required = "sales.view_payment"
    table_class = PaymentTable
    filterset_class = PaymentFilter
    page_title_key = "page_payments"
    page_subtitle_key = "page_payments_sub"
    allow_add = False


class InvoiceListView(ScopedListView):
    model = Invoice
    permission_required = "sales.view_invoice"
    table_class = InvoiceTable
    filterset_class = InvoiceFilter
    template_name = "sales/invoice_list.html"  # adds the row-action CSRF input
    page_title_key = "page_invoices"
    page_subtitle_key = "page_invoices_sub"
    allow_add = False  # creation is a full-page flow, not a modal

    def get_ribbon_action_specs(self):
        if not self.request.user.has_perm("sales.add_invoice"):
            return []
        strings = get_strings(get_current_language_code(self.request))
        return [{
            "url": reverse("sales:invoice_create"),
            "label": strings.get("ui_new_invoice", "New Invoice"),
            "icon": "bi bi-plus-lg",
            "css_class": "btn btn-primary rounded-pill",
        }]


# --------------------------------------------------------------------------- #
# Invoice editor (multi-line, full page)
# --------------------------------------------------------------------------- #
#: Bootstrap-Icons for service tiles in the picker (by service_type), used when a
#: service has no uploaded image — so services stay visually distinct in the grid.
SERVICE_TYPE_ICONS = {
    "installation": "bi-wrench",
    "maintenance": "bi-gear",
    "warranty": "bi-shield-check",
    "delivery": "bi-truck",
    "other": "bi-tools",
}


def _apply_item_price(item, invoice):
    """Derive frozen unit price / kind from the chosen product or service when
    the user didn't type a price explicitly."""
    if item.product_id:
        item.kind = item.KIND_PRODUCT
        item.service = None
        if item.variant_id:
            if item.variant.product_id != item.product_id:
                raise ValidationError(_("Selected color/size does not belong to the selected product."))
        else:
            color = item.color or ""
            size = (item.size or "").strip()
            matches = list(item.product.variants.filter(color=color, size=size))
            if len(matches) == 1:
                item.variant = matches[0]
            elif item.product.variants.count() == 1:
                item.variant = item.product.variants.first()
        if item.variant_id:
            item.color = item.variant.color or None
            item.size = item.variant.size or None
        else:
            item.color = item.color or item.product.color
            item.size = item.size or item.product.size
        if item.unit_price_lyd in (None, ""):
            item.unit_price_lyd = item.product.selling_price_lyd(invoice.exchange_rate) or Decimal("0")
        item.unit_price_usd = item.product.effective_price_usd
        item.unit_cost_usd = item.product.cost_usd  # freeze cost for exact COGS
    elif item.service_id:
        item.kind = item.KIND_SERVICE
        item.product = None
        item.variant = None
        item.color = None
        item.size = None
        item.unit_cost_usd = None  # services carry no goods cost
        if item.unit_price_lyd in (None, ""):
            item.unit_price_lyd = item.service.selling_price_lyd(invoice.exchange_rate) or Decimal("0")
        item.unit_price_usd = item.service.price_usd
    else:
        item.kind = item.KIND_CUSTOM
        item.variant = None
        item.color = None
        item.size = None
        if item.unit_price_lyd in (None, ""):
            item.unit_price_lyd = Decimal("0")


class _InvoiceEditorView(DocumentEditorView):
    """The POS invoice editor: header form + cart formset + the tile picker.

    The shared plumbing — atomic save, formset lifecycle, deleted lines, the
    audit entry — lives in `common.editors.DocumentEditorView`; what stays here
    is what is actually about invoices: the catalog payload, the frozen price
    rule, and binding the customer.
    """

    template_name = "sales/invoice_form.html"
    document_form = InvoiceForm
    item_formset = InvoiceItemFormSet
    picker_context_key = "catalog_map_json"

    def _catalog_map(self, rate):
        """JSON catalog for the POS-style item picker: in-stock products (with
        their in-stock colour/size variants) and services (each with a type icon
        or its own image). The client renders the tile grid and fills the hidden
        line fields from it; price stays editable in the cart row."""
        from catalog.models import Product, Service, product_color_hex

        products = []
        qs = Product.objects.filter(is_active=True).select_related("category").prefetch_related("variants")
        for p in qs:
            variants = [
                {
                    "id": v.pk,
                    "color": v.color or "",
                    "color_label": v.color_label,
                    "color_hex": product_color_hex(v.color),
                    "size": v.size or "",
                    "stock_qty": float(v.stock_qty or 0),
                    "label": v.display_label,
                }
                for v in p.variants.filter(stock_qty__gt=0).order_by("color", "size", "pk")
            ]
            # Only surface sellable items: a product with in-stock variants, or a
            # variant-less product that either has stock or isn't stock-tracked.
            has_stock = bool(variants) or (not p.track_stock) or (p.stock_qty or 0) > 0
            if variants or p.track_stock:
                if not has_stock:
                    continue
            products.append({
                "id": p.pk,
                "name": p.name,
                "category": p.category.name if p.category_id else "",
                "category_id": p.category_id or 0,
                "image": p.image_url,
                "price": float(p.selling_price_lyd(rate) or 0),
                "track_stock": bool(p.track_stock),
                "stock_qty": float(p.stock_qty or 0),
                "variants": variants,
            })

        services = []
        for s in Service.objects.filter(is_active=True):
            price = s.selling_price_lyd(rate)
            services.append({
                "id": s.pk,
                "name": s.name,
                "type": s.service_type,
                "type_label": s.get_service_type_display(),
                "icon": SERVICE_TYPE_ICONS.get(s.service_type, SERVICE_TYPE_ICONS["other"]),
                "image": s.image_url,
                "price": float(price) if price is not None else None,
            })
        return json.dumps({"products": products, "services": services})

    def _rate(self, invoice=None):
        return invoice.exchange_rate if invoice else get_current_rate()

    def picker_map(self):
        return self._catalog_map(self._rate(self.get_object()))

    def form_kwargs(self):
        return {"user": self.request.user}

    def extra_context(self, invoice=None):
        from catalog.models import Category

        return {
            # The template has always called it `invoice`, not `document`.
            "invoice": invoice,
            "current_rate": self._rate(invoice),
            "has_rate": has_configured_rate(),
            "categories": Category.objects.filter(is_active=True).order_by("name"),
            # Feeds the customer combobox <datalist> + JS autofill of phone/address.
            # Customers are private, so a rep only ever sees/binds their own book.
            "customers": apply_ownership(
                Customer.objects.filter(is_active=True), self.request.user
            ).order_by("name"),
        }

    def sync_counterparty(self, invoice, actor):
        # Customers are private, so a rep only ever matches or creates within
        # their own book — which is what the scoped queryset expresses.
        sync_party(
            invoice,
            prefix="customer",
            party_model=Customer,
            queryset=apply_ownership(Customer.objects.all(), actor),
        )

    def apply_document_defaults(self, invoice):
        # The rate is frozen onto the invoice, never typed: a draft saved today
        # and issued next week must still price at today's rate.
        if invoice.exchange_rate is None:
            invoice.exchange_rate = get_current_rate()

    def apply_line_defaults(self, item, invoice):
        _apply_item_price(item, invoice)

    def post_save(self, invoice):
        invoice.recalc_totals()

    def success_url(self, invoice):
        return reverse("sales:invoice_detail", args=[invoice.pk])


class InvoiceCreateView(_InvoiceEditorView):
    permission_required = "sales.add_invoice"

    def on_valid(self, request, invoice):
        messages.success(request, _("Invoice %(no)s saved as draft.") % {"no": invoice.number})


class InvoiceUpdateView(_InvoiceEditorView):
    permission_required = "sales.change_invoice"

    def get_object(self):
        # Ownership-scoped: a rep can only edit their own/assigned invoices.
        if not hasattr(self, "_invoice"):
            self._invoice = get_object_or_404(
                _visible_invoices(self.request.user), pk=self.kwargs["pk"]
            )
        return self._invoice

    def check_editable(self, request, invoice):
        # Both GET and POST: without the GET guard the editor renders happily
        # and only refuses on submit.
        if invoice is not None and not invoice.is_editable:
            messages.warning(request, _("Only draft invoices can be edited."))
            return redirect("sales:invoice_detail", pk=invoice.pk)
        return None

    def on_valid(self, request, invoice):
        messages.success(request, _("Invoice %(no)s updated.") % {"no": invoice.number})


# --------------------------------------------------------------------------- #
# Invoice detail + lifecycle actions
# --------------------------------------------------------------------------- #
class InvoiceDetailView(LoginRequiredMixin, PermissionRequiredMixin, DetailView):
    model = Invoice
    permission_required = "sales.view_invoice"
    raise_exception = True
    template_name = "sales/invoice_detail.html"
    context_object_name = "invoice"

    def get_queryset(self):
        return _visible_invoices(self.request.user)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        invoice = self.object
        ctx["items"] = invoice.items.all()
        ctx["payments"] = invoice.payments.all()
        ctx["payment_form"] = PaymentForm()
        # Feeds the deposit combobox <datalist> (search-and-add batches by reference).
        ctx["cash_deposits"] = scope_filtered_queryset(
            CashDeposit.objects.exclude(reference="").order_by("-deposited_at"),
            self.request.user,
        )
        return ctx


class InvoiceIssueView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = "sales.issue_invoice"
    raise_exception = True

    def post(self, request, pk):
        invoice = get_object_or_404(_visible_invoices(request.user), pk=pk)
        try:
            issue_invoice(invoice, request.user)
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
            return redirect("sales:invoice_detail", pk=pk)
        log_user_action(request, "ISSUE", instance=invoice)
        messages.success(request, _("Invoice %(no)s issued. Stock updated.") % {"no": invoice.number})
        return redirect("sales:invoice_detail", pk=pk)


class InvoiceCancelView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = "sales.cancel_invoice"
    raise_exception = True

    def post(self, request, pk):
        invoice = get_object_or_404(_visible_invoices(request.user), pk=pk)
        cancel_invoice(invoice, request.user)
        log_user_action(request, "CANCEL", instance=invoice)
        messages.warning(request, _("Invoice %(no)s cancelled.") % {"no": invoice.number})
        return redirect("sales:invoice_detail", pk=pk)


class InvoicePrintView(LoginRequiredMixin, PermissionRequiredMixin, DetailView):
    model = Invoice
    permission_required = "sales.view_invoice"
    raise_exception = True
    template_name = "sales/invoice_print.html"
    context_object_name = "invoice"

    def get_queryset(self):
        return _visible_invoices(self.request.user)

    def get_context_data(self, **kwargs):
        from dlux.translations import get_current_language_code

        ctx = super().get_context_data(**kwargs)
        ctx["items"] = self.object.items.all()
        ctx["payments"] = self.object.payments.all()
        lang = get_current_language_code(self.request)
        ctx["doc_lang"] = lang
        ctx["is_rtl"] = lang.startswith("ar")
        return ctx


class PaymentReceiptView(LoginRequiredMixin, PermissionRequiredMixin, DetailView):
    model = Payment
    permission_required = "sales.view_payment"
    raise_exception = True
    template_name = "sales/payment_receipt.html"
    context_object_name = "payment"

    def get_queryset(self):
        return _visible_payments(self.request.user)

    def get_context_data(self, **kwargs):
        from dlux.translations import get_current_language_code

        ctx = super().get_context_data(**kwargs)
        payment = self.object
        invoice = payment.invoice
        paid_through = (
            invoice.payments.filter(
                Q(paid_at__lt=payment.paid_at)
                | Q(paid_at=payment.paid_at, pk__lte=payment.pk)
            ).aggregate(t=Sum("amount"))["t"]
            or Decimal("0.00")
        )
        lang = get_current_language_code(self.request)
        ctx["invoice"] = invoice
        ctx["paid_before_receipt"] = quantize_lyd(paid_through - payment.amount)
        ctx["balance_after_receipt"] = quantize_lyd(invoice.total_lyd - paid_through)
        ctx["doc_lang"] = lang
        ctx["is_rtl"] = lang.startswith("ar")
        return ctx


class PaymentCreateView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = "sales.add_payment"
    raise_exception = True

    def post(self, request, pk):
        invoice = get_object_or_404(_visible_invoices(request.user), pk=pk)
        if invoice.status in (Invoice.STATUS_DRAFT, Invoice.STATUS_CANCELLED):
            messages.error(request, _("Issue the invoice before recording payments."))
            return redirect("sales:invoice_detail", pk=pk)
        form = PaymentForm(request.POST)
        if form.is_valid():
            payment = form.save(commit=False)
            payment.invoice = invoice
            self._sync_deposit(request, payment, form.cleaned_data.get("deposit_ref"))
            payment.save()  # recalc_payments + deposit recalc run in Payment.save()
            log_user_action(request, "PAYMENT", instance=invoice)
            messages.success(request, _("Payment recorded."))
        else:
            messages.error(request, _("Could not record payment. Check the amount."))
        return redirect("sales:invoice_detail", pk=pk)

    def _sync_deposit(self, request, payment, reference):
        """Bind the payment to a CashDeposit batch for the typed reference.

        A matched batch (hidden FK already set by JS) is used as-is; a new
        reference creates a pending batch so cash collected on the fly is grouped
        without pre-creating the deposit. The batch amount is auto-summed from its
        payments in ``CashDeposit.recalc_amount`` (triggered by ``Payment.save``).
        """
        if payment.deposit_id:
            return  # existing batch picked from the datalist
        reference = (reference or "").strip()
        if not reference:
            payment.deposit = None
            return
        qs = scope_filtered_queryset(CashDeposit.objects.all(), request.user)
        deposit = qs.filter(reference__iexact=reference).first()
        if deposit is None:
            # amount starts at 0 (NOT NULL) and is set to the batch total by
            # CashDeposit.recalc_amount() the moment payment.save() runs below.
            deposit = CashDeposit(reference=reference, method=payment.method, amount=Decimal("0.00"))
            deposit.save()  # scope / created_by come from the request (ScopedModel)
        payment.deposit = deposit


# --------------------------------------------------------------------------- #
# Sales-focused overview. The project-wide landing dashboard is /workspace/.
# --------------------------------------------------------------------------- #
class DashboardView(RibbonPageMixin, LoginRequiredMixin, TemplateView):
    template_name = "sales/dashboard.html"
    page_title_key = "sales_dashboard"
    page_subtitle_key = "page_sales_dashboard_sub"

    def get_ribbon_action_specs(self):
        strings = self.get_page_strings()
        return [
            {
                "url": reverse("sales:report"),
                "label": strings.get("ui_reports", "Reports"),
                "icon": "bi bi-graph-up",
                "css_class": "btn btn-outline-secondary rounded-pill",
                "permission": "sales.view_sales_report",
            },
            {
                "url": reverse("sales:financial_report"),
                "label": strings.get("page_financial_report", "Financial"),
                "icon": "bi bi-cash-stack",
                "css_class": "btn btn-outline-secondary rounded-pill",
                "permission": "sales.view_financial_report",
            },
            {
                "url": reverse("sales:invoice_create"),
                "label": strings.get("ui_new_invoice", "New Invoice"),
                "icon": "bi bi-plus-lg",
                "css_class": "btn btn-primary rounded-pill",
                "permission": "sales.add_invoice",
            },
        ]

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        today = timezone.localdate()
        month_start = today.replace(day=1)
        live_statuses = [Invoice.STATUS_ISSUED, Invoice.STATUS_PARTIAL, Invoice.STATUS_PAID]

        # Role-aware overview. Every panel is both permission-gated (a delivery
        # courier has no view_invoice) and row-scoped: a rep's figures cover only
        # their own sales, a manager (view_all_invoice) sees the whole store.
        ctx["can_view_sales"] = user.has_perm("sales.view_invoice")
        ctx["can_view_deliveries"] = user.has_perm("sales.view_delivery")
        ctx["is_sales_manager"] = user_can_view_all(user, Invoice)

        my_invoices = _visible_invoices(user)
        today_qs = my_invoices.filter(invoice_date=today, status__in=live_statuses)
        month_qs = my_invoices.filter(invoice_date__gte=month_start, status__in=live_statuses)

        ctx["current_rate"] = get_current_rate()
        ctx["has_rate"] = has_configured_rate()
        ctx["latest_rate_row"] = ExchangeRate.objects.order_by("-created_at").first()
        # External reference rates (scraped, cached) shown next to our custom rate:
        # the official CBL rate and the eanlibya black-market rate. Read cache-only
        # here — the web tier is network-isolated; the celery worker (which has
        # egress) does the scraping and populates the shared Redis cache.
        cbl = get_cbl_official_rate(refresh_if_missing=False)
        ctx["cbl_official"] = cbl
        if cbl and cbl.get("average"):
            ctx["cbl_official_rate"] = Decimal(str(cbl["average"]))

        ean = get_ean_black_market_rate(refresh_if_missing=False)
        ctx["ean_market"] = ean
        if ean and ean.get("rate"):
            market = Decimal(str(ean["rate"]))
            ctx["ean_market_rate"] = market
            # Custom pricing tracks the black market, so the meaningful gap is
            # custom vs black-market; fall back to the official rate if EAN is down.
            ctx["rate_gap"] = ctx["current_rate"] - market
        elif ctx.get("cbl_official_rate"):
            ctx["rate_gap"] = ctx["current_rate"] - ctx["cbl_official_rate"]
        ctx["sales_today"] = today_qs.aggregate(t=Sum("total_lyd"))["t"] or Decimal("0")
        ctx["count_today"] = today_qs.count()
        ctx["sales_month"] = month_qs.aggregate(t=Sum("total_lyd"))["t"] or Decimal("0")
        outstanding_qs = my_invoices.filter(status__in=[Invoice.STATUS_ISSUED, Invoice.STATUS_PARTIAL])
        ctx["outstanding"] = (outstanding_qs.aggregate(t=Sum("total_lyd"))["t"] or Decimal("0")) - (
            outstanding_qs.aggregate(t=Sum("amount_paid"))["t"] or Decimal("0")
        )
        ctx["draft_count"] = my_invoices.filter(status=Invoice.STATUS_DRAFT).count()
        ctx["pending_deposits"] = (
            apply_ownership(CashDeposit.objects.all(), user)
            .filter(status=CashDeposit.STATUS_PENDING)
            .count()
        )
        ctx["recent_invoices"] = my_invoices.order_by("-created_at")[:8]

        # Delivery board — the courier's own open jobs (or all, for a dispatcher).
        if ctx["can_view_deliveries"]:
            open_deliveries = apply_ownership(
                Delivery.objects.filter(status__in=Delivery.OPEN_STATUSES), user
            ).order_by("scheduled_date", "-created_at")
            ctx["open_deliveries"] = open_deliveries[:8]
            ctx["open_delivery_count"] = open_deliveries.count()

        # Low-stock is a catalog concern — only for users who can see products.
        if user.has_perm("catalog.view_product"):
            from catalog.models import Product

            low = [p for p in Product.objects.filter(track_stock=True, is_active=True) if p.is_low_stock]
            ctx["low_stock"] = low[:8]
            ctx["low_stock_count"] = len(low)
        return ctx


# --------------------------------------------------------------------------- #
# Sales reporting (+ XLSX export)
# --------------------------------------------------------------------------- #
class SalesReportView(RibbonPageMixin, LoginRequiredMixin, PermissionRequiredMixin, TemplateView):
    permission_required = "sales.view_sales_report"
    raise_exception = True
    template_name = "sales/report.html"
    page_title_key = "ui_sales_report"
    page_subtitle_key = "page_sales_report_sub"

    def get_window(self):
        if not hasattr(self, "_window"):
            self._window = parse_window(
                self.request.GET.get("date_from"), self.request.GET.get("date_to")
            )
        return self._window

    def get_ribbon_action_specs(self):
        """The XLSX export, carrying the window the page is currently showing."""
        date_from, date_to = self.get_window()
        query = urlencode({
            "date_from": date_from.strftime("%Y-%m-%d"),
            "date_to": date_to.strftime("%Y-%m-%d"),
        })
        return [{
            "url": f"{reverse('sales:report_export')}?{query}",
            "label": self.get_page_strings().get("ui_export_xlsx", "Export XLSX"),
            "icon": "bi bi-file-earmark-excel",
            "css_class": "btn btn-success rounded-pill",
        }]

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        date_from, date_to = self.get_window()
        ctx["report"] = build_sales_report(date_from, date_to, self.request.user)
        ctx["date_from"] = date_from
        ctx["date_to"] = date_to
        return ctx


class FinancialReportView(RibbonPageMixin, LoginRequiredMixin, PermissionRequiredMixin, TemplateView):
    """Whole-store fiscal-year P&L (owner/manager). Not row-scoped — its own
    permission gates it (COGS / margins / capital-in-stock are sensitive)."""

    permission_required = "sales.view_financial_report"
    raise_exception = True
    template_name = "sales/financial_report.html"
    page_title_key = "page_financial_report"
    page_subtitle_key = "page_financial_report_sub"

    def get_years(self):
        if not hasattr(self, "_years"):
            self._years = available_fiscal_years()
        return self._years

    def get_year(self):
        years = self.get_years()
        try:
            year = int(self.request.GET.get("year", ""))
        except (TypeError, ValueError):
            return years[0]
        return year if year in years else years[0]

    def get_ribbon_action_specs(self):
        """The fiscal-year picker.

        Raw `html` rather than a button: it is a GET form that reloads the page
        on change, and the ribbon has no filter band here — this view has no
        FilterSet to derive one from.
        """
        strings = self.get_page_strings()
        selected = self.get_year()
        options = format_html_join(
            "", '<option value="{}"{}>{}</option>',
            ((y, mark_safe(' selected') if y == selected else "", y) for y in self.get_years()),
        )
        return [{
            "html": format_html(
                '<form method="get" class="d-flex align-items-center gap-2 no-print">'
                '<label class="text-muted small mb-0" for="fiscal-year">{}</label>'
                '<select id="fiscal-year" name="year" class="form-select form-select-sm w-auto"'
                ' onchange="this.form.submit()">{}</select></form>',
                strings.get("ui_fiscal_year", "Fiscal year"),
                options,
            ),
        }]

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        years = self.get_years()
        year = self.get_year()
        date_from, date_to = fiscal_year_window(year)
        ctx["report"] = build_financial_report(date_from, date_to)
        ctx["year"] = year
        ctx["years"] = years
        return ctx


class SalesReportExportView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = "sales.view_sales_report"
    raise_exception = True

    def get(self, request):
        date_from, date_to = parse_window(request.GET.get("date_from"), request.GET.get("date_to"))
        report = build_sales_report(date_from, date_to, request.user)
        content = build_sales_report_xlsx(report)
        log_user_action(request, "EXPORT", model_name="Sales Report")
        response = HttpResponse(
            content,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = (
            f'attachment; filename="sales_report_{date_from}_{date_to}.xlsx"'
        )
        return response
