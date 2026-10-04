import json
from decimal import Decimal

from django import forms
from django.forms import formset_factory
from django.utils.html import format_html, format_html_join

from dlux.forms import ManagedAssetFormMixin
from dlux.translations import get_strings
from dlux.utils import set_field_attrs

from common.forms import (
    QUANTITY_INPUT_ATTRS, apply_dlux_file_widgets, build_grid_helper, translate_choice_fields,
    translate_help_text,
)
from finance.services import get_current_rate, has_configured_rate
from finance.currency import CURRENCY_CHOICES, active_currencies, pricing_currency

from .models import (
    Category, Product, ProductBarcode, PurchaseInvoice, Service, StockMovement, Supplier, PRODUCT_COLOR_SWATCHES,
)


COLOR_SWATCHES = PRODUCT_COLOR_SWATCHES


class ColorPaletteWidget(forms.Widget):
    input_type = "hidden"

    def __init__(self, attrs=None, choices=()):
        super().__init__(attrs)
        self.choices = list(choices) or list(Product.COLOR_CHOICES)

    def render(self, name, value, attrs=None, renderer=None):
        from common.i18n import t

        value = value or ""
        attrs = self.build_attrs(self.attrs, attrs)
        input_attrs = dict(attrs)
        if "id" not in input_attrs:
            input_attrs["id"] = f"id_{name}"
        hidden = forms.HiddenInput().render(name, value, input_attrs, renderer=renderer)
        options = []
        for option_value, fallback_label in self.choices:
            label = t(f"color_{option_value}", fallback_label)
            bg = COLOR_SWATCHES.get(option_value, "#ffffff")
            border = "#111111" if option_value == Product.COLOR_WHITE else bg
            options.append((option_value, label, bg, border))
        buttons = format_html_join(
            "",
            '<button type="button" class="color-swatch" data-color-value="{}" data-color-label="{}" '
            'title="{}" aria-label="{}" '
            'style="width:1.45rem;height:1.45rem;margin:0 .18rem .18rem 0;border:2px solid {};'
            'border-radius:999px;background:{};box-shadow:inset 0 0 0 1px rgba(255,255,255,.45);"></button>',
            ((option_value, label, label, label, border, bg) for option_value, label, bg, border in options),
        )
        current_label = t("ui_no_color", "No color")
        current_bg = "transparent"
        current_border = "var(--bs-border-color,#adb5bd)"
        for option_value, label, bg, border in options:
            if option_value == value:
                current_label = label
                current_bg = bg
                current_border = border
                break
        return format_html(
            '<div class="color-palette-widget position-relative" data-color-palette data-empty-label="{}">{}'
            '<button type="button" class="btn btn-sm btn-outline-secondary w-100 d-flex align-items-center justify-content-between gap-2" data-color-trigger>'
            '<span class="d-inline-flex align-items-center gap-2">'
            '<span data-color-current-swatch style="display:inline-block;width:1rem;height:1rem;border-radius:999px;border:2px solid {};background:{}"></span>'
            '<span data-color-current-label>{}</span>'
            '</span><i class="bi bi-chevron-down"></i></button>'
            '<div class="color-palette-popover shadow border rounded bg-body p-2" data-color-popover hidden '
            'style="position:absolute;z-index:1080;min-width:12rem;max-width:14rem;inset-inline-start:0;top:calc(100% + .25rem)">{}'
            '<button type="button" class="btn btn-sm btn-link px-1 py-0" data-color-value="" data-color-label="{}">{}</button>'
            '</div></div>',
            t("ui_no_color", "No color"),
            hidden,
            current_border,
            current_bg,
            current_label,
            buttons,
            t("ui_clear_color", "Clear color"),
            t("ui_clear_color", "Clear color"),
        )


def _use_dlux_image_widget(form):
    """Every file field on the form gets dlux's uploader, images accept-gated.

    ``accept="image/*"`` reaches the underlying input, so a phone still offers
    camera-or-gallery. ``show_scan`` is left off — that button is dlux's desktop
    TWAIN scanner (ScanLink), not the mobile camera. Call after
    ``set_field_attrs`` so the captured label is already translated.
    """
    apply_dlux_file_widgets(form, accept={"image": "image/*"})
    # A managed-asset picker is not a plain file field, so the helper above
    # leaves its tag label unset and the widget falls back to the field name.
    for field in form.fields.values():
        if hasattr(field.widget, "field_label") and not field.widget.field_label:
            field.widget.field_label = field.label


def _use_dlux_document_widget(form):
    """Rich file input for supporting purchase-invoice scans/photos/PDFs."""
    apply_dlux_file_widgets(
        form,
        accept={"attachment": "image/*,application/pdf"},
        show_scan=("attachment",),
    )


def _tag_lyd_field(form, field_name):
    """Expose the live USD→LYD rate on a widget so the price-sync JS can preview
    the LYD selling price as the user types (see catalog/js/price_sync.js)."""
    if field_name in form.fields:
        form.fields[field_name].widget.attrs["data-usd-rate"] = str(get_current_rate())


class CategoryForm(forms.ModelForm):
    # Reload the parent list page after a successful dynamic-modal save.
    refresh_parent = True

    class Meta:
        model = Category
        fields = ["name", "parent", "is_service", "description", "is_active"]

    def __init__(self, *args, request=None, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        from common.views import scope_filtered_queryset
        user = user or getattr(request, "user", None)
        if user is not None:
            self.fields["parent"].queryset = scope_filtered_queryset(self.fields["parent"].queryset, user)
            if not self.instance.pk:
                from dlux.utils import get_user_scope, is_scope_enabled
                if is_scope_enabled():
                    self.instance.scope = get_user_scope(user)
        if self.instance.pk:
            self.fields["parent"].queryset = self.fields["parent"].queryset.filter(scope_id=self.instance.scope_id).exclude(pk__in=self.instance.descendant_ids())
        set_field_attrs(self)
        translate_help_text(self)
        build_grid_helper(self, [("name", "is_active"), ("parent", "is_service"), "description"])


class SupplierForm(forms.ModelForm):
    refresh_parent = True

    class Meta:
        model = Supplier
        fields = ["name", "phone", "address", "notes", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        set_field_attrs(self)
        translate_help_text(self)
        build_grid_helper(self, [("name", "phone"), ("address", "is_active"), ("notes",)])


class ProductForm(ManagedAssetFormMixin, forms.ModelForm):
    refresh_parent = True
    #: A stored file predating the asset library is adopted on first save.
    legacy_asset_files = {"image_asset": "image"}
    #: A clerk photographing stock wants the camera, not the file browser.
    asset_capture = "environment"

    class Meta:
        model = Product
        # stock_qty is intentionally excluded: stock is driven by StockMovement so
        # the ledger stays authoritative. Use a "Stock In" movement to seed quantity.
        fields = [
            "name", "alias", "currency", "sku", "category", "barcode", "image_asset", "unit",
            "description",
            "cost_usd", "markup_percent", "price_usd", "price_lyd_override",
            "track_stock", "reorder_level", "is_active",
        ]

    def __init__(self, *args, request=None, user=None, **kwargs):
        # `request` is taken for the optional automotive extension only; it is not
        # stored as `self.request`, which would change managed-asset attribution.
        super().__init__(*args, **kwargs)
        from automotive.product_form import AutomotiveProductExtension

        self.fields["category"].queryset = self.fields["category"].queryset.filter(is_service=False)
        self.automotive = AutomotiveProductExtension.attach(self, request)
        from machinery.forms import attach_machine_models
        self.has_machinery = attach_machine_models(self, user or getattr(request, "user", None), self.instance, request)
        codes = ", ".join(self.instance.extra_barcodes.values_list("code", flat=True)) if self.instance.pk else ""
        self.fields["extra_barcodes"] = forms.CharField(
            required=False, initial=codes, label=get_strings().get("label_extra_barcodes", "Extra barcodes"),
            help_text=get_strings().get("help_extra_barcodes", "Other codes that should find this item, separated by commas."),
        )
        # A code scanned at the till that matched nothing arrives here to pre-fill.
        scanned = getattr(request, "GET", {}).get("barcode") if request is not None else None
        if scanned and not self.is_bound and not self.instance.pk:
            self.initial["barcode"] = scanned[:64]
        self.fields["currency"].required = False
        if len(active_currencies()) == 1:
            self.fields["currency"].widget = forms.HiddenInput()
            self.fields["currency"].disabled = True
        self.fields["currency"].widget.attrs.update({
            "data-product-currency": "1",
            "data-currency-rates": json.dumps({code: str(get_current_rate(code)) for code, _ in CURRENCY_CHOICES}),
        })
        self.fields["sku"].required = False
        # Data hooks the price-sync JS keys off (see catalog/js/price_sync.js).
        self.fields["cost_usd"].widget.attrs["data-price-cost"] = "1"
        self.fields["markup_percent"].widget.attrs["data-price-markup"] = "1"
        self.fields["price_usd"].widget.attrs["data-price-usd"] = "1"
        self.fields["price_lyd_override"].widget.attrs["data-price-lyd"] = "1"
        _tag_lyd_field(self, "price_lyd_override")
        set_field_attrs(self)
        translate_choice_fields(self)
        translate_help_text(self)
        # set_field_attrs seeds a placeholder from the label; the JS repurposes the
        # LYD field's placeholder to show the live derived price, so clear it here.
        self.fields["price_lyd_override"].widget.attrs.pop("placeholder", None)
        _use_dlux_image_widget(self)
        self.fields["cost_usd"].label = get_strings().get("ui_doc_cost", "Cost")
        self.fields["price_usd"].label = get_strings().get("ui_doc_price", "Selling price")
        for name in ("cost_usd", "price_usd"):
            self.fields[name].widget.attrs["placeholder"] = self.fields[name].label
        rows = [
            ("name", "sku"),
            ("alias",) if self.fields["currency"].widget.is_hidden else ("alias", "currency"),
            ("category", "unit"),
            ("barcode", "extra_barcodes"),
            ("image_asset",),
            ("cost_usd", "markup_percent", "price_usd"),
            ("price_lyd_override", "reorder_level"),
            ("track_stock", "is_active"),
            ("description",),
        ]
        if self.has_machinery:
            rows.insert(3, ("machine_models",))
        if self.automotive:
            rows = self.automotive.layout(rows)
        build_grid_helper(self, rows)

    def clean_currency(self):
        currency = self.cleaned_data.get("currency") or self.instance.currency or pricing_currency()
        if currency != self.instance.currency and currency not in active_currencies():
            raise forms.ValidationError(get_strings().get("purchase_currency_inactive", "This currency is not active."))
        if self.instance.pk and currency != self.instance.currency:
            if not all(has_configured_rate(code) for code in (currency, self.instance.currency)):
                raise forms.ValidationError(get_strings().get("purchase_currency_rates", "Set exchange rates for both currencies first."))
        return currency

    def clean(self):
        cleaned_data = super().clean()
        if self.automotive:
            self.automotive.clean(cleaned_data)
        self._clean_extra_barcodes(cleaned_data)
        return cleaned_data

    def _clean_extra_barcodes(self, cleaned_data):
        codes = []
        for raw in (cleaned_data.get("extra_barcodes") or "").replace("\n", ",").split(","):
            code = raw.strip()
            if code and code not in codes and code != cleaned_data.get("barcode"):
                codes.append(code[:64])
        taken = ProductBarcode.objects.filter(code__in=codes)
        products = Product.objects.filter(barcode__in=codes)
        if self.instance.pk:
            taken = taken.exclude(product=self.instance)
            products = products.exclude(pk=self.instance.pk)
        clash = sorted(set(taken.values_list("code", flat=True)) | set(products.values_list("barcode", flat=True)))
        if clash:
            self.add_error("extra_barcodes", get_strings().get(
                "error_barcode_taken", "Already used by another item: {codes}",
            ).format(codes=", ".join(clash)))
        cleaned_data["extra_barcodes"] = codes

    def _save_m2m(self):
        super()._save_m2m()
        from machinery.forms import save_machine_models
        save_machine_models(self, self.instance)
        if self.automotive:
            self.automotive.save(self.instance)
        wanted = self.cleaned_data.get("extra_barcodes") or []
        for barcode in self.instance.extra_barcodes.all():
            if barcode.code not in wanted:
                barcode.delete()
        have = set(self.instance.extra_barcodes.values_list("code", flat=True))
        for code in wanted:
            if code not in have:
                ProductBarcode.objects.create(product=self.instance, scope=self.instance.scope, code=code)


class ServiceForm(ManagedAssetFormMixin, forms.ModelForm):
    refresh_parent = True
    legacy_asset_files = {"image_asset": "image"}
    asset_capture = "environment"

    class Meta:
        model = Service
        fields = ["name", "category", "service_type", "image_asset", "description", "price_usd", "price_lyd_override", "is_active"]

    def __init__(self, *args, request=None, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        from machinery.forms import attach_machine_models
        self.has_machinery = attach_machine_models(self, user or getattr(request, "user", None), self.instance, request)
        self.fields["price_usd"].widget.attrs["data-price-usd"] = "1"
        self.fields["price_lyd_override"].widget.attrs["data-price-lyd"] = "1"
        _tag_lyd_field(self, "price_lyd_override")
        set_field_attrs(self)
        translate_choice_fields(self)
        translate_help_text(self)
        self.fields["price_lyd_override"].widget.attrs.pop("placeholder", None)
        _use_dlux_image_widget(self)
        rows = [
            ("name", "service_type"),
            ("image_asset",),
            ("price_usd", "price_lyd_override", "is_active"),
            ("description",),
        ]
        if self.has_machinery:
            rows.insert(1, ("category", "machine_models"))
        else:
            self.fields.pop("category", None)
        build_grid_helper(self, rows)

    def _save_m2m(self):
        super()._save_m2m()
        from machinery.forms import save_machine_models
        save_machine_models(self, self.instance)


class VariantProductSelect(forms.Select):
    variant_product_map = {}

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex=subindex, attrs=attrs)
        raw = getattr(value, "value", value)
        product_id = self.variant_product_map.get(str(raw))
        if product_id is not None:
            option["attrs"]["data-product"] = str(product_id)
        return option


class StockMovementForm(forms.ModelForm):
    refresh_parent = True

    class Meta:
        model = StockMovement
        fields = ["product", "variant", "movement_type", "quantity", "reason", "reference"]
        widgets = {"variant": VariantProductSelect}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        variant_field = self.fields["variant"]
        variant_field.widget.variant_product_map = {
            str(pk): pid for pk, pid in variant_field.queryset.values_list("pk", "product_id")
        }
        set_field_attrs(self)
        self.fields["quantity"].widget.attrs.update(QUANTITY_INPUT_ATTRS)
        translate_choice_fields(self)
        translate_help_text(self)
        build_grid_helper(self, [("product", "variant"), ("movement_type", "quantity"), ("reference",), ("reason",)])

    def clean(self):
        cleaned = super().clean()
        product = cleaned.get("product")
        variant = cleaned.get("variant")
        if product and variant and variant.product_id != product.pk:
            self.add_error("variant", get_strings().get("ui_invalid_product_variant", "Choose a variant for the selected product."))
        return cleaned


class PurchaseInvoiceForm(forms.ModelForm):
    """Purchase invoice header. The visible supplier name is a datalist-backed
    combobox; the hidden FK is filled when the typed supplier already exists."""

    class Meta:
        model = PurchaseInvoice
        fields = [
            "supplier", "supplier_name", "supplier_phone", "supplier_address",
            "invoice_date", "currency", "attachment", "notes",
        ]
        widgets = {
            "invoice_date": forms.DateInput(attrs={"type": "date"}),
            "supplier": forms.HiddenInput(),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["currency"].required = False
        self.fields["currency"].initial = pricing_currency()
        self.can_choose_currency = user is not None and user.has_perm("catalog.add_purchaseinvoice")
        self.fields["currency"].choices = [(code, code) for code in active_currencies()]
        self.fields["currency"].disabled = not self.can_choose_currency or len(active_currencies()) == 1
        if self.fields["currency"].disabled:
            self.fields["currency"].widget = forms.HiddenInput()
        self.fields["supplier"].required = False
        self.fields["supplier_name"].required = True
        self.fields["supplier_name"].widget.attrs.update({
            "list": "supplier-datalist",
            "autocomplete": "off",
            "data-supplier-input": "1",
        })
        set_field_attrs(self)
        translate_help_text(self)
        _use_dlux_document_widget(self)
        build_grid_helper(self, [
            ("supplier_name", "supplier_phone"),
            ("supplier_address", "invoice_date"),
            ("currency",),
            ("notes",),
            ("attachment",),
        ])

    def clean_currency(self):
        currency = self.cleaned_data.get("currency") or pricing_currency()
        raw = self.data.get(self.add_prefix("currency")) if self.is_bound else None
        if self.fields["currency"].disabled and raw and raw != pricing_currency():
            raise forms.ValidationError(get_strings().get("purchase_currency_denied", "You cannot select this purchase currency."))
        if currency != pricing_currency() and not has_configured_rate(currency):
            raise forms.ValidationError(get_strings().get("purchase_currency_rates", "Set exchange rates for both currencies first."))
        return currency


class OpeningStockLineForm(forms.Form):
    """One row of the one-time opening-stock grid. Deliberately **not** a
    ModelForm — a row spans creating/reusing a ``Product`` and posting a Stock In
    ``StockMovement``, both done in the view; there is no opening-stock model.
    The visible ``name`` doubles as a new-or-existing product combobox: JS matches
    it against existing products, fills the hidden ``product`` id (blank = a
    brand-new item), and autofills cost/markup/price from the product map."""

    product = forms.IntegerField(required=False, widget=forms.HiddenInput())
    name = forms.CharField(required=False, max_length=200)
    alias = forms.CharField(required=False, max_length=200)
    currency = forms.ChoiceField(required=False, choices=CURRENCY_CHOICES)
    category = forms.ModelChoiceField(queryset=Category.objects.filter(is_service=False), required=False)
    unit = forms.ChoiceField(choices=Product.UNIT_CHOICES, initial=Product.UNIT_PIECE)
    barcode = forms.CharField(required=False, max_length=64)
    color = forms.ChoiceField(required=False, choices=[("", "---------"), *Product.COLOR_CHOICES], widget=ColorPaletteWidget(choices=Product.COLOR_CHOICES))
    size = forms.CharField(required=False, max_length=120)
    cost_usd = forms.DecimalField(required=False, min_value=0, max_digits=12, decimal_places=2, initial=Decimal("0"))
    markup_percent = forms.DecimalField(required=False, min_value=0, max_digits=6, decimal_places=2, initial=Decimal("0"))
    price_usd = forms.DecimalField(required=False, min_value=0, max_digits=12, decimal_places=2, initial=Decimal("0"))
    price_lyd_override = forms.DecimalField(required=False, min_value=0, max_digits=14, decimal_places=2)
    quantity = forms.DecimalField(required=False, min_value=0, max_digits=12, decimal_places=2, initial=Decimal("0"))

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        from machinery.forms import attach_machine_models
        attach_machine_models(self, user)
        from common.i18n import t

        s = get_strings()
        labels = {
            "name": s.get("label_product_name", "Name"),
            "alias": s.get("label_product_alias", "Local alias"),
            "currency": s.get("label_product_currency", "Product currency"),
            "category": s.get("label_product_category", "Category"),
            "unit": s.get("label_product_unit", "Unit"),
            "barcode": s.get("label_product_barcode", "Barcode"),
            "color": s.get("label_product_color", "Color"),
            "size": s.get("label_product_size", "Size / Spec"),
            "cost_usd": s.get("ui_doc_cost", "Cost"),
            "markup_percent": s.get("label_product_markup_percent", "Markup %"),
            "price_usd": s.get("ui_doc_price", "Selling price"),
            "price_lyd_override": s.get("label_product_price_lyd_override", "Manual LYD Price"),
            "quantity": s.get("label_openingstockline_quantity", "Qty in Storage"),
        }
        for name, label in labels.items():
            self.fields[name].label = label
        # Translate the unit choices to the active language.
        self.fields["unit"].choices = [(v, t(f"unit_{v}", lbl)) for v, lbl in Product.UNIT_CHOICES]
        # Combobox + price-sync hooks (same data-* the invoice/product forms use).
        self.fields["name"].widget.attrs.update({
            "list": "product-datalist", "autocomplete": "off", "data-product-input": "1",
        })
        self.fields["cost_usd"].widget.attrs["data-price-cost"] = "1"
        self.fields["markup_percent"].widget.attrs["data-price-markup"] = "1"
        self.fields["price_usd"].widget.attrs["data-price-usd"] = "1"
        self.fields["price_lyd_override"].widget.attrs["data-price-lyd"] = "1"
        self.fields["price_lyd_override"].widget.attrs["data-usd-rate"] = str(get_current_rate())
        if len(active_currencies()) == 1:
            self.fields["currency"].widget = forms.HiddenInput()
            self.fields["currency"].initial = pricing_currency()
        self.fields["currency"].initial = pricing_currency()
        self.fields["currency"].widget.attrs.update({
            "data-product-currency": "1",
            "data-currency-rates": json.dumps({code: str(get_current_rate(code)) for code, _ in CURRENCY_CHOICES}),
        })
        # Self-contained Bootstrap styling (no ModelForm, so set_field_attrs doesn't apply).
        for name, field in self.fields.items():
            w = field.widget
            if isinstance(w, forms.HiddenInput):
                continue
            if isinstance(w, forms.Select):
                w.attrs.setdefault("class", "form-select form-select-sm")
            else:
                w.attrs.setdefault("class", "form-control form-control-sm")
                if field.label:
                    w.attrs.setdefault("placeholder", field.label)
        self.fields["quantity"].widget.attrs.update(QUANTITY_INPUT_ATTRS)


    def clean(self):
        cleaned = super().clean()
        if cleaned.get("DELETE"):
            return cleaned
        product = Product.objects.filter(pk=cleaned.get("product")).first() if cleaned.get("product") else None
        if product is None and cleaned.get("name"):
            product = Product.objects.filter(name__iexact=cleaned["name"]).first()
        currency = cleaned.get("currency")
        if currency and currency not in active_currencies() and (product is None or currency != product.currency):
            self.add_error("currency", get_strings().get("purchase_currency_inactive", "This currency is not active."))
        return cleaned


class PurchaseInvoiceLineForm(OpeningStockLineForm):
    """Purchase-line row with the same product autofill/price-sync controls as
    Opening Stock, but a filled row must carry a positive purchased quantity."""

    def __init__(self, *args, user=None, invoice_currency=None, **kwargs):
        super().__init__(*args, user=user, **kwargs)
        self.invoice_currency = invoice_currency or pricing_currency()
        self.fields["price_lyd_override"].widget.attrs["data-usd-rate"] = str(get_current_rate(self.invoice_currency))
        self.fields["currency"].widget.attrs.pop("data-product-currency", None)
        self.fields["currency"].initial = self.invoice_currency
        s = get_strings()
        self.fields["quantity"].label = s.get("label_purchaseinvoiceline_quantity", "Qty Purchased")
        self.fields["quantity"].widget.attrs["placeholder"] = self.fields["quantity"].label
        from automotive.product_form import attach_line_fits

        self.fits_user = user
        self.fits_enabled = attach_line_fits(self, user)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("DELETE"):
            return cleaned
        product = Product.objects.filter(pk=cleaned.get("product")).first() if cleaned.get("product") else None
        currency = cleaned.get("currency") or (product.currency if product else self.invoice_currency)
        if currency != (product.currency if product else self.invoice_currency) and currency not in active_currencies():
            self.add_error("currency", get_strings().get("purchase_currency_inactive", "This currency is not active."))
        if currency != self.invoice_currency and not all(has_configured_rate(code) for code in (currency, self.invoice_currency)):
            self.add_error("currency", get_strings().get("purchase_currency_rates", "Set exchange rates for both currencies first."))
        if self.fits_enabled:
            from automotive.product_form import clean_line_fits

            clean_line_fits(self, cleaned, self.fits_user)
        has_data = any(
            cleaned.get(name)
            for name in (
                "product", "name", "category", "barcode", "cost_usd", "markup_percent",
                "color", "size", "price_usd",
                "price_lyd_override", "quantity",
            )
        )
        if not has_data:
            return cleaned
        if not (cleaned.get("name") or "").strip():
            self.add_error("name", get_strings().get("ui_required_product_name", "Enter a product name."))
        if not cleaned.get("quantity") or cleaned["quantity"] <= 0:
            self.add_error("quantity", get_strings().get("ui_required_positive_quantity", "Enter a quantity greater than zero."))
        return cleaned


# Plain formset powering the multi-row opening-stock grid (add-row JS mirrors the
# invoice item grid). Fully-empty rows are ignored; blank-name rows are dropped
# in the view.
OpeningStockLineFormSet = formset_factory(OpeningStockLineForm, extra=1, can_delete=True)
PurchaseInvoiceLineFormSet = formset_factory(PurchaseInvoiceLineForm, extra=0, can_delete=True)
