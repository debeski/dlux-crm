"""
Reusable view building blocks shared by every domain app.

The slick DjangoLux pattern for simple models is: a single permission-gated
``ListView`` per model, with create/edit/view/delete handled by the framework's
dynamic modal manager (``modal_manager``) which auto-resolves ``<Model>Form``.
``ScopedListView`` wires that whole surface up in a few lines, so the apps stay
thin and consistent.
"""
from decimal import Decimal

from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.exceptions import FieldDoesNotExist
from django.db.models import Sum
from django.urls import reverse
from django.utils import timezone
from django_filters.views import FilterView
from django_tables2 import SingleTableMixin
from django.views.generic import TemplateView

from dlux.ribbon import RibbonMixin, build_action
from dlux.translations import get_current_language_code, get_strings
from dlux.utils import get_user_scope, is_scope_enabled

from common.access import apply_ownership
from common.formatting import format_money
from common.forms import translate_choice_fields


def _money(value):
    return format_money(value)


def _count(value):
    return f"{value:,}"


def _pct(value):
    return max(0, min(100, int(value or 0)))


def _tile(
    tile_id, title, icon, kind="metric", size="m", value=None, unit="", meta="",
    url="", tone="neutral", progress=None, items=None, actions=None, footer="",
):
    return {
        "id": tile_id,
        "title": title,
        "icon": icon,
        "kind": kind,
        "size": size,
        "value": value,
        "unit": unit,
        "meta": meta,
        "url": url,
        "tone": tone,
        "progress": progress,
        "items": items or [],
        "actions": actions or [],
        "footer": footer,
    }


def _config_names(entries):
    """Flatten a FilterSet ``advanced_config`` section into filter names.

    Entries are a name, a ``{"name": ...}`` dict carrying presentation hints, or
    a nested list standing for one rendered row. Only the names survive: the
    Ribbon derives placeholders and From/To range labels itself, from the field
    names and the `_gte`/`_lte` suffix convention.
    """
    names = []
    for entry in entries or ():
        if isinstance(entry, (list, tuple)):
            names.extend(_config_names(entry))
        elif isinstance(entry, dict):
            name = entry.get("name")
            if name:
                names.append(name)
        elif entry:
            names.append(str(entry))
    return names


def scope_filtered_queryset(queryset, user):
    """Defence-in-depth scope guard (the ScopedManager already scopes; this keeps
    parity with the dlux scaffold and protects custom querysets)."""
    if not is_scope_enabled() or getattr(user, "is_superuser", False):
        return queryset
    try:
        queryset.model._meta.get_field("scope")
    except FieldDoesNotExist:
        return queryset
    user_scope = get_user_scope(user)
    if user_scope is None:
        return queryset.none()
    return queryset.filter(scope=user_scope)


class RibbonPageMixin(RibbonMixin):
    """A dlux ribbon on a page that is not a scoped list.

    Reports, dashboards and the public-site builders have a heading and a row
    of actions like every list does, but no model, table or FilterSet — so the
    ribbon here carries a title, a description and whatever the page's own
    buttons are. Titles use the same ``page_title_key`` / ``page_subtitle_key``
    contract the lists use, so a string is named the same wherever it lives.

    The template renders it with ``{% dlux_ribbon %}``.
    """

    page_title_key = ""
    page_subtitle_key = ""
    page_title = ""
    page_subtitle = ""

    def get_page_strings(self):
        return get_strings(get_current_language_code(self.request))

    def get_ribbon_title(self):
        strings = self.get_page_strings()
        return (self.page_title_key and strings.get(self.page_title_key)) or self.page_title or ""

    def get_ribbon_subtitle(self):
        strings = self.get_page_strings()
        return (self.page_subtitle_key and strings.get(self.page_subtitle_key)) or self.page_subtitle or ""

    def get_ribbon_actions(self):
        """Same contract as the list pages: specs in, `RibbonAction`s out.

        A bare dict has neither `is_html` nor `is_link`, which the ribbon
        template dispatches on, so every spec goes through `build_action`.
        """
        built = [
            action
            for action in (
                build_action(spec, request=self.request)
                for spec in self.get_ribbon_action_specs()
            )
            if action is not None
        ]
        return built + list(super().get_ribbon_actions())

    def get_ribbon_action_specs(self):
        return []

    #: Set by `refresh_ribbon()` — the page context an action's markup needs.
    ribbon_page_context = None

    def refresh_ribbon(self, context):
        """Rebuild the ribbon once the page's own context exists.

        `RibbonMixin` builds it inside `super().get_context_data()`, which runs
        *before* a subclass adds anything — fine for a title and a link, not for
        an action whose markup is one of the page's own stateful controls. A
        view with such an action calls this at the end of `get_context_data`.
        """
        self.ribbon_page_context = context
        context[self.ribbon_context_key] = self.get_ribbon(context)
        return context


class ScopedListView(RibbonMixin, LoginRequiredMixin, PermissionRequiredMixin, SingleTableMixin, FilterView):
    """Standard list page: filter form + DluxTable + a permission-gated "Add"
    button that opens the framework dynamic-modal create form.

    Subclasses set ``model``, ``table_class``, ``filterset_class``,
    ``permission_required`` and (optionally) ``page_title`` / ``page_subtitle``.
    """

    #: Left False so Django's AccessMixin splits the two cases the way a user
    #: expects: an anonymous visitor — most often somebody whose session simply
    #: expired — is sent to the login page, while a signed-in user who lacks the
    #: permission gets 403. Setting it True gave *everyone* a bare 403, so an
    #: expired session looked like a permissions problem.
    raise_exception = False
    template_name = "common/scoped_list.html"
    ordering = "-created_at"
    #: DLUX_STRINGS keys (preferred — bilingual). Fall back to the literals below.
    page_title_key = ""
    page_subtitle_key = ""
    page_title = ""
    page_subtitle = ""
    #: set False for models that should not be created from the list page
    allow_add = True
    #: Extra query keys that are not filters but must survive a filter submit
    #: and a Clear. The ribbon adds its own strip's key automatically; a
    #: hand-drawn second strip names its key here.
    ribbon_preserve_keys = ("sort", "page")
    #: static paths (relative to STATIC_URL) appended to the page's scripts block —
    #: e.g. per-model modal-form enhancers. Loaded on the list page so they are
    #: present when its create/edit modal opens.
    extra_scripts = ()
    extra_styles = ()
    #: Shared by every scoped list, emitted ahead of a subclass's own entries so
    #: the CRUD wiring stays beneath what a view overrides. `scoped_crud.js`
    #: reads the `data-scoped-crud` attributes `common/scoped_list.html` puts on
    #: the list wrapper and drives the create/edit/view/delete dynamic modals;
    #: `ribbon_actions.css` repairs a `.btn-group` sitting in the ribbon.
    base_styles = ("common/css/ribbon_actions.css",)
    base_scripts = ("common/js/scoped_crud.js",)

    def get_queryset(self):
        # Through super() rather than straight to the manager: RibbonMixin sits
        # first in the MRO and narrows by the active ribbon tab there. Starting
        # from the manager skipped it, so a declared tab strip rendered but did
        # not filter, and every tabbed list had to narrow by hand.
        qs = super().get_queryset()
        if self.ordering:
            order = [self.ordering] if isinstance(self.ordering, str) else list(self.ordering)
            qs = qs.order_by(*order)
        qs = scope_filtered_queryset(qs, self.request.user)
        # Row-level visibility: an employee sees only their own records unless
        # they hold the model's view_all_<model> permission (see common.access).
        return apply_ownership(qs, self.request.user)

    def get_filterset(self, filterset_class):
        filterset = super().get_filterset(filterset_class)
        # The Ribbon derives the whole filter band from the FilterSet, but it
        # does not touch the choices *inside* a field, so the option labels
        # (status/method/… -> Arabic/English) are still localized here.
        translate_choice_fields(filterset.form, self.request)
        return filterset

    def get_ribbon_actions(self):
        """Build this page's action specs into `RibbonAction`s.

        The ribbon template dispatches on `action.is_html` / `action.is_link`,
        which are properties on `RibbonAction` — a bare dict has neither, so it
        renders as an empty `<button>` however well-formed the dict is. Every
        spec therefore goes through `build_action`, which also marks raw `html`
        safe and applies the spec's own `permission` / `permissions` gate.
        """
        built = [
            action
            for action in (
                build_action(spec, request=self.request)
                for spec in self.get_ribbon_action_specs()
            )
            if action is not None
        ]
        return built + list(super().get_ribbon_actions())

    def get_ribbon_action_specs(self):
        """Action dicts for this list — the Add button by default.

        An action with a `url` renders as a link and one without renders as a
        button, so a modal opener carries only its `data-dynamic-modal` attrs.
        """
        opts = self.model._meta
        strings = get_strings(get_current_language_code(self.request))
        can_add = self.allow_add and self.request.user.has_perm(
            f"{opts.app_label}.add_{opts.model_name}"
        )
        if not can_add:
            return []
        label = strings.get("ui_add", "Add")
        return [{
            "label": label,
            "icon": "bi bi-plus-lg",
            "css_class": "btn btn-primary rounded-pill",
            "attrs": {
                "data-dynamic-modal": self.get_add_modal_url(),
                "data-modal-title": label,
            },
        }]

    def get_ribbon_title(self):
        return self.get_context_data_titles()[0]

    def get_ribbon_subtitle(self):
        return self.get_context_data_titles()[1]

    @property
    def ribbon_primary(self):
        """Which filters sit in the ribbon's own row, not the advanced panel.

        Read from the FilterSet's ``advanced_config`` — the layout each one has
        always declared beside the fields it describes. Without this the Ribbon
        would infer, and it promotes only ``keyword``/``q``/``search`` and
        ``year``: every status and method dropdown these lists keep in the front
        row would quietly move into the advanced panel.
        """
        return _config_names(self._filter_layout().get("fields")) or None

    @property
    def ribbon_advanced(self):
        return _config_names(self._filter_layout().get("advanced_fields")) or None

    def _filter_layout(self):
        return getattr(self.filterset_class, "advanced_config", None) or {}

    def get_ribbon_preserve_keys(self):
        keys = list(self.ribbon_preserve_keys or ())
        for key in self._filter_layout().get("clear_preserve_keys") or ():
            if key not in keys:
                keys.append(key)
        return tuple(keys)

    def get_context_data_titles(self):
        """``(title, subtitle)`` for the page, resolved once.

        Both the Ribbon and the template need them, and duplicating this
        fallback chain is how the two paths drift apart.
        """
        opts = self.model._meta
        strings = get_strings(get_current_language_code(self.request))
        title = (
            (self.page_title_key and strings.get(self.page_title_key))
            or self.page_title
            or strings.get(f"model_{opts.model_name}")
            or str(opts.verbose_name_plural).title()
        )
        subtitle = (
            (self.page_subtitle_key and strings.get(self.page_subtitle_key))
            or self.page_subtitle
        )
        return title, subtitle

    def get_add_modal_url(self):
        opts = self.model._meta
        # Form-only modal (show_table=False) — see config.urls scoped_modal_manager.
        return reverse("scoped_modal_manager", args=[opts.app_label, opts.object_name, "new"])

    def get_modal_base_url(self):
        """Template URL with a ``__pk__`` placeholder the row-action JS swaps for
        a record id to open its form-only edit/view modal."""
        opts = self.model._meta
        return reverse("scoped_modal_manager", args=[opts.app_label, opts.object_name, "__pk__"])

    def get_modal_delete_url(self):
        opts = self.model._meta
        return reverse("scoped_modal_delete", args=[opts.app_label, opts.object_name, "__pk__"])

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        opts = self.model._meta
        strings = get_strings(get_current_language_code(self.request))
        can_add = self.allow_add and self.request.user.has_perm(
            f"{opts.app_label}.add_{opts.model_name}"
        )
        title, subtitle = self.get_context_data_titles()
        context.update(
            {
                "page_title": title,
                "page_subtitle": subtitle,
                "add_modal_url": self.get_add_modal_url() if can_add else None,
                "add_label": strings.get("ui_add", "Add"),
                "model_verbose_name": opts.verbose_name,
                # Consumed by scoped_crud.js to open form-only edit/view/delete modals.
                "modal_base_url": self.get_modal_base_url(),
                "modal_delete_url": self.get_modal_delete_url(),
                "extra_scripts": [*self.base_scripts, *self.extra_scripts],
                "extra_styles": [*self.base_styles, *self.extra_styles],
            }
        )
        return context


class WorkspaceDashboardView(LoginRequiredMixin, TemplateView):
    """Project-wide operational dashboard.

    The server decides which tiles exist based on permissions and ownership
    scopes. Presentation preferences (order, hidden state, size) are persisted
    in the user's DLux app-preferences namespace, with localStorage only kept as
    a fallback for runtimes without the app-preference endpoint.
    """

    template_name = "common/workspace_dashboard.html"

    def _strings(self):
        return get_strings(get_current_language_code(self.request))

    def _s(self, key, fallback):
        return self._strings().get(key, fallback)

    def _status_counts(self, invoices):
        from sales.models import Invoice

        return {
            status: invoices.filter(status=status).count()
            for status in (
                Invoice.STATUS_DRAFT,
                Invoice.STATUS_ISSUED,
                Invoice.STATUS_PARTIAL,
                Invoice.STATUS_PAID,
                Invoice.STATUS_CANCELLED,
            )
        }

    def _build_quick_actions(self):
        user = self.request.user
        candidates = [
            (("sales.add_invoice",), "ui_new_invoice", "New Invoice", "bi bi-receipt", "sales:invoice_create"),
            (
                ("catalog.add_purchaseinvoice", "catalog.add_product", "catalog.change_product", "catalog.add_stockmovement"),
                "ui_add_stock", "Add Stock", "bi bi-box-arrow-in-down", "catalog:purchase_invoice_create",
            ),
            (("catalog.add_stocktake",), "ui_new_stock_take", "New Count", "bi bi-clipboard-check", "catalog:stock_take_create"),
            (("finance.add_exchangerate",), "page_exchange_rates", "Exchange Rates", "bi bi-currency-exchange", "finance:exchange_rate_list"),
            (("finance.add_expense",), "page_expenses", "Expenses", "bi bi-receipt-cutoff", "finance:expense_list"),
            (("finance.add_staffledgerentry",), "page_staff_ledger_entries", "Staff Ledger", "bi bi-person-lines-fill", "finance:staff_ledger_entry_list"),
            (("sales.view_sales_report",), "ui_sales_report", "Sales Report", "bi bi-graph-up", "sales:report"),
            (("sales.view_financial_report",), "page_financial_report", "Financial", "bi bi-cash-stack", "sales:financial_report"),
        ]
        actions = []
        for perms, key, fallback, icon, url_name in candidates:
            if all(user.has_perm(perm) for perm in perms):
                actions.append({
                    "label": self._s(key, fallback),
                    "icon": icon,
                    "url": reverse(url_name),
                })
        return actions

    def _sales_tiles(self, today, month_start):
        from sales.models import Customer, Invoice, Payment

        user = self.request.user
        tiles = []
        if user.has_perm("sales.view_invoice"):
            live_statuses = [Invoice.STATUS_ISSUED, Invoice.STATUS_PARTIAL, Invoice.STATUS_PAID]
            invoices = apply_ownership(scope_filtered_queryset(Invoice.objects.all(), user), user)
            today_qs = invoices.filter(invoice_date=today, status__in=live_statuses)
            month_qs = invoices.filter(invoice_date__gte=month_start, status__in=live_statuses)
            outstanding_qs = invoices.filter(status__in=[Invoice.STATUS_ISSUED, Invoice.STATUS_PARTIAL])
            sales_today = today_qs.aggregate(t=Sum("total_lyd"))["t"] or Decimal("0.00")
            sales_month = month_qs.aggregate(t=Sum("total_lyd"))["t"] or Decimal("0.00")
            outstanding = (outstanding_qs.aggregate(t=Sum("total_lyd"))["t"] or Decimal("0.00")) - (
                outstanding_qs.aggregate(t=Sum("amount_paid"))["t"] or Decimal("0.00")
            )
            progress = (sales_today / sales_month * Decimal("100")) if sales_month else Decimal("0")
            status_counts = self._status_counts(invoices)

            tiles.extend([
                _tile(
                    "sales_today", self._s("ui_sales_today", "Sales Today"), "bi bi-lightning-charge",
                    value=_money(sales_today), unit="LYD",
                    meta=f"{today_qs.count()} {self._s('ui_invoices_word', 'invoice(s)')}",
                    url=reverse("sales:invoice_list"), tone="green", progress=_pct(progress),
                ),
                _tile(
                    "sales_month", self._s("ui_sales_month", "Sales This Month"), "bi bi-calendar3",
                    value=_money(sales_month), unit="LYD",
                    meta=f"{month_qs.count()} {self._s('ui_invoices_word', 'invoice(s)')}",
                    url=reverse("sales:report") if user.has_perm("sales.view_sales_report") else reverse("sales:invoice_list"),
                    tone="blue", progress=100 if sales_month else 0,
                ),
                _tile(
                    "receivables", self._s("ui_outstanding", "Outstanding"), "bi bi-hourglass-split",
                    value=_money(outstanding), unit="LYD",
                    meta=f"{status_counts.get(Invoice.STATUS_DRAFT, 0)} {self._s('ui_drafts', 'draft(s)')}",
                    url=reverse("sales:invoice_list"), tone="red",
                ),
            ])

            recent_items = []
            for inv in invoices.order_by("-created_at")[:6]:
                recent_items.append({
                    "label": inv.number or "—",
                    "meta": inv.display_customer,
                    "value": f"{_money(inv.total_lyd)} LYD",
                    "url": reverse("sales:invoice_detail", args=[inv.pk]),
                    "badge": inv.status_label,
                    "tone": inv.status,
                })
            tiles.append(_tile(
                "recent_invoices", self._s("ui_recent_invoices", "Recent Invoices"), "bi bi-receipt",
                kind="list", size="l", items=recent_items, url=reverse("sales:invoice_list"),
                footer=(
                    self._s("ui_view_all", "View all")
                    if recent_items else self._s("ui_no_invoices", "No invoices yet.")
                ),
                tone="blue",
            ))

            pipeline_items = [
                {"label": self._s("status_draft", "Draft"), "value": _count(status_counts.get(Invoice.STATUS_DRAFT, 0)), "tone": "draft"},
                {"label": self._s("status_issued", "Issued"), "value": _count(status_counts.get(Invoice.STATUS_ISSUED, 0)), "tone": "issued"},
                {"label": self._s("status_partial", "Partially Paid"), "value": _count(status_counts.get(Invoice.STATUS_PARTIAL, 0)), "tone": "partial"},
                {"label": self._s("status_paid", "Paid"), "value": _count(status_counts.get(Invoice.STATUS_PAID, 0)), "tone": "paid"},
            ]
            tiles.append(_tile(
                "sales_pipeline", self._s("ui_sales_pipeline", "Sales Pipeline"), "bi bi-kanban",
                kind="compact-list", size="m", items=pipeline_items, url=reverse("sales:invoice_list"),
                tone="cyan",
            ))

        if user.has_perm("sales.view_payment"):
            payments = apply_ownership(
                scope_filtered_queryset(Payment.objects.select_related("invoice"), user), user
            )
            paid_today = payments.filter(paid_at__date=today).aggregate(t=Sum("amount"))["t"] or Decimal("0.00")
            tiles.append(_tile(
                "cash_today", self._s("ui_cash_collected_today", "Cash Collected Today"),
                "bi bi-cash-coin", value=_money(paid_today), unit="LYD",
                meta=f"{payments.filter(paid_at__date=today).count()} {self._s('ui_payments', 'Payments')}",
                url=reverse("sales:payment_list"), tone="amber",
            ))

        if user.has_perm("sales.view_customer"):
            customers = apply_ownership(
                scope_filtered_queryset(Customer.objects.filter(is_active=True), user), user
            )
            tiles.append(_tile(
                "customer_book", self._s("page_customers", "Customers"), "bi bi-people",
                value=_count(customers.count()), meta=self._s("ui_active_records", "active records"),
                url=reverse("sales:customer_list"), tone="violet",
            ))
        return tiles

    def _delivery_tiles(self):
        from sales.models import Delivery

        user = self.request.user
        if not user.has_perm("sales.view_delivery"):
            return []
        open_deliveries = apply_ownership(
            scope_filtered_queryset(Delivery.objects.filter(status__in=Delivery.OPEN_STATUSES), user), user
        ).order_by("scheduled_date", "-created_at")
        today = timezone.localdate()
        items = []
        for delivery in open_deliveries[:6]:
            items.append({
                "label": delivery.recipient or delivery.address,
                "meta": delivery.scheduled_date or "—",
                "value": delivery.status_label,
                "url": reverse("sales:delivery_list"),
                "tone": delivery.status,
            })
        return [
            _tile(
                "deliveries", self._s("page_deliveries", "Deliveries"), "bi bi-truck",
                value=_count(open_deliveries.count()),
                meta=f"{open_deliveries.filter(scheduled_date=today).count()} {self._s('ui_due_today', 'due today')}",
                url=reverse("sales:delivery_list"), tone="teal",
            ),
            _tile(
                "delivery_board", self._s("ui_delivery_board", "Delivery Board"), "bi bi-signpost-split",
                kind="list", size="m", items=items, url=reverse("sales:delivery_list"),
                footer=(
                    self._s("ui_view_all", "View all")
                    if items else self._s("ui_no_deliveries", "No open deliveries.")
                ),
                tone="teal",
            ),
        ]

    def _catalog_tiles(self):
        from catalog.models import Product, PurchaseInvoice, StockMovement, StockTake, Supplier
        from finance.services import usd_to_lyd

        user = self.request.user
        tiles = []
        if user.has_perm("catalog.view_product"):
            products = scope_filtered_queryset(Product.objects.filter(is_active=True), user)
            product_count = products.count()
            low_stock = [p for p in products.filter(track_stock=True) if p.is_low_stock]
            tiles.append(_tile(
                "products", self._s("page_products", "Products & Stock"), "bi bi-box-seam",
                value=_count(product_count), meta=f"{len(low_stock)} {self._s('ui_low_stock', 'Low Stock')}",
                url=reverse("catalog:product_list"), tone="indigo",
                progress=_pct((product_count - len(low_stock)) / product_count * 100) if product_count else 0,
            ))
            low_items = [
                {
                    "label": p.name,
                    "meta": p.category.name if p.category_id else "",
                    "value": f"{p.stock_qty:g}",
                    "url": reverse("catalog:product_list"),
                    "tone": "danger",
                }
                for p in low_stock[:6]
            ]
            tiles.append(_tile(
                "low_stock", self._s("ui_low_stock", "Low Stock"), "bi bi-exclamation-triangle",
                kind="list", size="m", items=low_items, url=reverse("catalog:product_list"),
                footer=self._s("ui_stock_healthy", "All stock levels are healthy.") if not low_items else self._s("ui_view_all", "View all"),
                tone="red",
            ))

        if user.has_perm("catalog.view_inventory_valuation"):
            total_usd = Decimal("0.00")
            valued_products = scope_filtered_queryset(
                Product.objects.filter(is_active=True, track_stock=True), user
            )
            for product in valued_products:
                total_usd += (product.stock_qty or Decimal("0")) * (product.cost_usd or Decimal("0"))
            tiles.append(_tile(
                "inventory_value", self._s("inventory_valuation", "Inventory Valuation"),
                "bi bi-safe2", value=_money(usd_to_lyd(total_usd)), unit="LYD",
                meta=f"{_money(total_usd)} USD", url=reverse("catalog:inventory_valuation"),
                tone="green",
            ))

        if user.has_perm("catalog.view_purchaseinvoice"):
            today = timezone.localdate()
            month_start = today.replace(day=1)
            purchases = scope_filtered_queryset(PurchaseInvoice.objects.all(), user)
            month_total = purchases.filter(invoice_date__gte=month_start).aggregate(t=Sum("total_lyd"))["t"] or Decimal("0.00")
            items = [
                {
                    "label": inv.number,
                    "meta": inv.display_supplier,
                    "value": f"{_money(inv.total_lyd)} LYD",
                    "url": reverse("catalog:purchase_invoice_detail", args=[inv.pk]),
                    "badge": inv.status_label,
                    "tone": inv.status,
                }
                for inv in purchases.order_by("-created_at")[:6]
            ]
            tiles.extend([
                _tile(
                    "purchase_month", self._s("ui_purchase_month", "Purchases This Month"),
                    "bi bi-box-arrow-in-down", value=_money(month_total), unit="LYD",
                    meta=f"{purchases.filter(invoice_date__gte=month_start).count()} {self._s('page_purchase_invoices', 'Purchase Invoices')}",
                    url=reverse("catalog:purchase_invoice_list"), tone="purple",
                ),
                _tile(
                    "recent_purchases", self._s("page_purchase_invoices", "Purchase Invoices"),
                    "bi bi-journal-arrow-down", kind="list", size="l", items=items,
                    url=reverse("catalog:purchase_invoice_list"), footer=self._s("ui_view_all", "View all"),
                    tone="purple",
                ),
            ])

        if user.has_perm("catalog.view_supplier"):
            suppliers = scope_filtered_queryset(Supplier.objects.filter(is_active=True), user)
            tiles.append(_tile(
                "suppliers", self._s("page_suppliers", "Suppliers"), "bi bi-buildings",
                value=_count(suppliers.count()), meta=self._s("ui_active_records", "active records"),
                url=reverse("catalog:supplier_list"), tone="cyan",
            ))

        if user.has_perm("catalog.view_stockmovement"):
            today = timezone.localdate()
            movements = scope_filtered_queryset(StockMovement.objects.all(), user)
            opening_used = movements.filter(reference="OPENING").exists()
            tiles.append(_tile(
                "stock_ledger", self._s("page_stock_movements", "Stock Movements"),
                "bi bi-arrow-left-right", value=_count(movements.filter(created_at__date=today).count()),
                meta=self._s("ui_movements_today", "movements today"),
                url=reverse("catalog:stock_movement_list"), tone="slate",
                footer=self._s("ui_view_opening_stock", "View Opening Stock") if opening_used else self._s("ui_new_opening_stock", "Opening Stock (bulk)"),
            ))

        if user.has_perm("catalog.view_stocktake"):
            takes = scope_filtered_queryset(StockTake.objects.all(), user)
            open_count = takes.filter(status=StockTake.STATUS_OPEN).count()
            tiles.append(_tile(
                "stock_takes", self._s("page_stock_takes", "Stock Takes"), "bi bi-clipboard-data",
                value=_count(open_count), meta=self._s("stocktake_status_open", "Open"),
                url=reverse("catalog:stock_take_list"), tone="amber",
            ))
        return tiles

    def _finance_tiles(self):
        from finance.models import CashDeposit, Expense, StaffAccount, StaffLedgerEntry
        from finance.services import (
            get_cbl_official_rate, get_current_rate, get_ean_black_market_rate,
            has_configured_rate,
        )

        user = self.request.user
        tiles = []
        current_rate = get_current_rate()
        cbl = get_cbl_official_rate(refresh_if_missing=False)
        ean = get_ean_black_market_rate(refresh_if_missing=False)
        ref_rate = None
        ref_label = self._s("ui_unavailable", "Unavailable")
        if ean and ean.get("rate"):
            ref_rate = Decimal(str(ean["rate"]))
            ref_label = self._s("ui_black_market_rate", "Black Market (EAN)")
        elif cbl and cbl.get("average"):
            ref_rate = Decimal(str(cbl["average"]))
            ref_label = self._s("ui_official_rate", "Official (CBL)")
        gap = current_rate - ref_rate if ref_rate is not None else None

        if user.has_perm("finance.view_exchangerate") or user.has_perm("sales.view_invoice") or user.has_perm("catalog.view_product"):
            tiles.append(_tile(
                "exchange_rate", self._s("ui_exchange_rate", "Exchange Rate"),
                "bi bi-currency-exchange", kind="rate", value=f"{current_rate}", unit="LYD/USD",
                meta=f"{ref_label}{': ' + str(ref_rate) if ref_rate is not None else ''}",
                url=reverse("finance:exchange_rate_list") if user.has_perm("finance.view_exchangerate") else "",
                tone="blue",
                footer=f"{self._s('ui_rate_gap', 'Gap')}: {gap:+.2f}" if gap is not None else "",
            ))
            if not has_configured_rate():
                tiles.append(_tile(
                    "rate_warning", self._s("ui_rate_warning_title", "Rate Needed"),
                    "bi bi-exclamation-circle", value=self._s("ui_no_rate_set", "(no rate set!)"),
                    meta=self._s("ui_rate_warning", "No exchange rate has been set yet."),
                    url=reverse("finance:exchange_rate_list") if user.has_perm("finance.view_exchangerate") else "",
                    tone="red",
                ))

        if user.has_perm("finance.view_cashdeposit"):
            deposits = apply_ownership(scope_filtered_queryset(CashDeposit.objects.all(), user), user)
            pending = deposits.filter(status=CashDeposit.STATUS_PENDING)
            pending_total = pending.aggregate(t=Sum("amount"))["t"] or Decimal("0.00")
            tiles.append(_tile(
                "cash_deposits", self._s("page_cash_deposits", "Cash Deposits"),
                "bi bi-wallet2", value=_money(pending_total), unit="LYD",
                meta=f"{pending.count()} {self._s('status_pending', 'Pending')}",
                url=reverse("finance:cash_deposit_list"), tone="amber",
            ))

        if user.has_perm("finance.view_expense"):
            today = timezone.localdate()
            month_start = today.replace(day=1)
            expenses = apply_ownership(scope_filtered_queryset(Expense.objects.all(), user), user)
            posted_month = expenses.filter(
                status=Expense.STATUS_POSTED,
                expense_date__gte=month_start,
            )
            month_total = posted_month.aggregate(t=Sum("amount_lyd"))["t"] or Decimal("0.00")
            tiles.append(_tile(
                "expenses_month", self._s("ui_expenses_month", "Expenses This Month"),
                "bi bi-receipt-cutoff", value=_money(month_total), unit="LYD",
                meta=f"{posted_month.count()} {self._s('page_expenses', 'Expenses')}",
                url=reverse("finance:expense_list"), tone="red",
            ))

        if user.has_perm("finance.view_staffaccount"):
            accounts = apply_ownership(
                scope_filtered_queryset(StaffAccount.objects.select_related("user"), user), user
            )
            account = accounts.filter(user=user).first()
            if account:
                url = reverse("finance:staff_account_detail", args=[account.pk])
                value = _money(account.balance_lyd)
                pending_count = account.pending_count
                meta = f"{pending_count} {self._s('status_pending', 'Pending')}"
            else:
                url = reverse("finance:staff_account_list")
                value = _count(accounts.count())
                pending_count = apply_ownership(
                    scope_filtered_queryset(StaffLedgerEntry.objects.all(), user), user
                ).filter(status=StaffLedgerEntry.STATUS_PENDING_USER).count()
                meta = f"{pending_count} {self._s('status_pending', 'Pending')}"
            tiles.append(_tile(
                "staff_account", self._s("page_staff_accounts", "Staff Accounts"),
                "bi bi-person-vcard", value=value, unit="LYD" if account else "",
                meta=meta, url=url, tone="violet",
            ))
        return tiles

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        today = timezone.localdate()
        month_start = today.replace(day=1)

        tiles = []
        tiles.extend(self._finance_tiles())
        tiles.extend(self._sales_tiles(today, month_start))
        tiles.extend(self._delivery_tiles())
        tiles.extend(self._catalog_tiles())

        quick_actions = self._build_quick_actions()
        if quick_actions:
            tiles.insert(0, _tile(
                "quick_actions", self._s("ui_quick_actions", "Quick Actions"), "bi bi-command",
                kind="actions", size="m", actions=quick_actions, tone="neutral",
            ))

        user_key = getattr(self.request.user, "pk", "anonymous") or "anonymous"
        ctx.update({
            "workspace_tiles": tiles,
            "workspace_storage_key": f"switch.workspace.dashboard.v1.{user_key}",
            "workspace_tile_count": len(tiles),
        })
        return ctx
