from django import forms
from django.contrib.auth import get_user_model
from django.forms import inlineformset_factory

from dlux.translations import get_strings
from dlux.utils import set_field_attrs

from common.forms import QUANTITY_INPUT_ATTRS, build_grid_helper, translate_choice_fields, translate_help_text

from .models import Customer, Delivery, Invoice, InvoiceItem, Payment

User = get_user_model()


def _staff_queryset():
    """Active users eligible to be picked as a salesperson / courier."""
    return User.objects.filter(is_active=True).order_by("first_name", "username")


class CustomerForm(forms.ModelForm):
    # Reload the parent list page after a successful dynamic-modal save.
    refresh_parent = True

    class Meta:
        model = Customer
        fields = ["name", "phone", "address", "notes", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        set_field_attrs(self)
        translate_help_text(self)
        build_grid_helper(self, [("name", "phone"), ("address", "is_active"), ("notes",)])


class InvoiceForm(forms.ModelForm):
    """Invoice header. The frozen ``exchange_rate`` is assigned by the view, not
    typed by the user."""

    class Meta:
        model = Invoice
        fields = [
            "salesperson",
            "customer", "customer_name", "customer_phone", "customer_address",
            "invoice_date", "discount_percent", "discount_amount", "notes",
        ]
        widgets = {
            "invoice_date": forms.DateInput(attrs={"type": "date"}),
            # The FK is a hidden companion to the visible name combobox; JS fills
            # it with the matched customer's pk (blank for a brand-new walk-in).
            "customer": forms.HiddenInput(),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["customer"].required = False
        # The salesperson picker is manager-only (assign_salesperson). For a
        # regular rep the field is dropped entirely — the invoice defaults to
        # them (Invoice.save / the editor view), so they can't reassign it away.
        can_assign = user is not None and user.has_perm("sales.assign_salesperson")
        if can_assign:
            self.fields["salesperson"].required = False
            self.fields["salesperson"].queryset = _staff_queryset()
        else:
            self.fields.pop("salesperson", None)
        # Single search-and-add combobox: a text input backed by <datalist> of
        # existing customers (rendered in the template). autocomplete is off so
        # the datalist — not the browser history — drives suggestions.
        self.fields["customer_name"].widget.attrs.update({
            "list": "customer-datalist",
            "autocomplete": "off",
            "data-customer-input": "1",
        })
        set_field_attrs(self)
        translate_help_text(self)
        # Multi-column layout for the invoice HEADER (the items grid is a
        # separate formset in the template). The template renders this with the
        # {% crispy form %} tag (the |crispy filter would drop this helper). The
        # hidden customer FK is emitted by build_grid_helper as a bare input.
        build_grid_helper(self, [
            ("salesperson", "invoice_date"),
            ("customer_name", "customer_phone"),
            ("customer_address",),
            ("discount_percent", "discount_amount"),
            ("notes",),
        ])


class InvoiceItemForm(forms.ModelForm):
    class Meta:
        model = InvoiceItem
        fields = [
            "kind", "product", "service", "description", "variant", "color", "size",
            "unit_price_lyd", "quantity",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from catalog.models import ProductVariant

        # The item, variant, colour and size are chosen in the catalog picker and
        # written into hidden inputs; only price and quantity stay editable in the
        # cart row (description is editable for free-text "custom" lines only).
        for name in ("kind", "product", "service", "variant", "color", "size", "description", "unit_price_lyd"):
            self.fields[name].required = False
        self.fields["variant"].queryset = ProductVariant.objects.select_related("product").all()
        for name in ("kind", "product", "service", "variant", "color", "size"):
            self.fields[name].widget = forms.HiddenInput()
        self.fields["description"].widget = forms.TextInput(attrs={
            "class": "form-control form-control-sm cart-desc d-none",
            "placeholder": get_strings().get("ui_custom_line_name", "Custom item description"),
        })
        self.fields["unit_price_lyd"].widget = forms.NumberInput(attrs={
            "class": "form-control form-control-sm text-end cart-price", "step": "0.01", "min": "0",
            "inputmode": "decimal",
        })
        self.fields["quantity"].widget = forms.NumberInput(attrs={
            "class": "form-control form-control-sm text-end cart-qty", "min": "0.01",
            **QUANTITY_INPUT_ATTRS,
        })
        translate_help_text(self)

    def clean(self):
        cleaned = super().clean()
        product = cleaned.get("product")
        variant = cleaned.get("variant")
        color = cleaned.get("color") or ""
        size = (cleaned.get("size") or "").strip()
        raw_quantity = self.data.get(self.add_prefix("quantity")) if self.is_bound else None
        has_line_data = bool(product or cleaned.get("service") or cleaned.get("description") or cleaned.get("unit_price_lyd") or color or size)
        if has_line_data and raw_quantity in (None, "") and not self.errors.get("quantity"):
            self.add_error("quantity", self.fields["quantity"].error_messages["required"])
        if not product:
            return cleaned
        variants = list(product.variants.all())
        if variant and variant.product_id != product.pk:
            self.add_error("color", get_strings().get("ui_invalid_product_variant", "Choose an available color/size for this product."))
            return cleaned
        if not variant and variants:
            available = [v for v in variants if v.stock_qty > 0]
            matching = [v for v in variants if (v.color or "") == color and (v.size or "") == size]
            if len(matching) == 1:
                cleaned["variant"] = matching[0]
            elif len(available) == 1:
                cleaned["variant"] = available[0]
            else:
                self.add_error("color", get_strings().get("ui_required_product_variant", "Choose an available color/size."))
        return cleaned


# Inline formset that powers the multi-line invoice editor.
InvoiceItemFormSet = inlineformset_factory(
    Invoice,
    InvoiceItem,
    form=InvoiceItemForm,
    extra=0,
    can_delete=True,
)


class PaymentForm(forms.ModelForm):
    # Search-and-add combobox for the optional cash-deposit batch, mirroring the
    # customer field: a <datalist>-backed text input whose value is a deposit
    # reference. JS fills the hidden ``deposit`` FK when the text matches an
    # existing batch; a new reference creates one on save (see _sync_deposit).
    deposit_ref = forms.CharField(required=False)

    class Meta:
        model = Payment
        # paid_at is intentionally excluded: it's set from the model default
        # (timezone.now) on save. Including it made the inline quick-pay form —
        # which only renders amount/method/deposit — fail "paid_at is required".
        fields = ["amount", "method", "deposit", "notes"]
        widgets = {"deposit": forms.HiddenInput()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["deposit"].required = False
        strings = get_strings()
        self.fields["deposit_ref"].label = strings.get("label_payment_deposit", "Cash Deposit")
        if self.instance.pk and self.instance.deposit_id:
            self.fields["deposit_ref"].initial = self.instance.deposit.reference
        self.fields["deposit_ref"].widget.attrs.update({
            "list": "deposit-datalist",
            "autocomplete": "off",
            "data-deposit-input": "1",
            "placeholder": strings.get("ui_deposit_search", "Search or add a deposit…"),
        })
        set_field_attrs(self)
        translate_choice_fields(self)
        translate_help_text(self)


class DeliveryForm(forms.ModelForm):
    """Dynamic-modal form for the delivery board. The ``assigned_to`` courier
    picker is dispatcher-only (``assign_delivery``); a courier editing their own
    job can update the status/notes but not hand it to someone else."""

    refresh_parent = True

    class Meta:
        model = Delivery
        fields = [
            "invoice", "assigned_to", "recipient", "phone", "address",
            "status", "scheduled_date", "notes",
        ]
        widgets = {"scheduled_date": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["invoice"].required = False
        can_assign = user is not None and user.has_perm("sales.assign_delivery")
        if can_assign:
            self.fields["assigned_to"].required = False
            self.fields["assigned_to"].queryset = _staff_queryset()
        else:
            self.fields.pop("assigned_to", None)
        set_field_attrs(self)
        translate_choice_fields(self)
        translate_help_text(self)
        build_grid_helper(self, [
            ("invoice", "assigned_to"),
            ("recipient", "phone"),
            ("address", "status"),
            ("scheduled_date",),
            ("notes",),
        ])
