import uuid
from decimal import Decimal

from django import forms

from common.forms import build_grid_helper
from dlux.utils import set_field_attrs
from common.i18n import t
from .models import Payment, PaymentResolution


class CancellationForm(forms.Form):
    payment_action = forms.ChoiceField()
    refund_method = forms.ChoiceField(required=False)
    notes = forms.CharField(max_length=255, required=False)

    def __init__(self, *args, invoice, **kwargs):
        super().__init__(*args, **kwargs)
        strings = {
            "later": t("cancel_later", "Resolve later — money owed to customer"),
            "refund": t("cancel_refund", "Refund payments"),
            "credit": t("cancel_credit", "Keep as customer credit"),
        }
        self.fields["payment_action"].label = t("cancel_payment_action", "Payments on this invoice")
        self.fields["payment_action"].choices = [(key, value) for key, value in strings.items() if key != "credit" or invoice.customer_id]
        self.fields["payment_action"].initial = "later"
        self.fields["refund_method"].label = t("cancel_refund_method", "Refund method")
        self.fields["refund_method"].choices = [("", "—")] + [(key, t(f"method_{key}", label)) for key, label in Payment.METHOD_CHOICES]
        self.fields["notes"].label = t("label_payment_notes", "Notes")
        set_field_attrs(self)
        build_grid_helper(self, [("payment_action",), ("refund_method",), ("notes",)])

    def clean(self):
        data = super().clean()
        if data.get("payment_action") == "refund" and not data.get("refund_method"):
            self.add_error("refund_method", t("cancel_method_required", "Choose the refund payment method."))
        return data


class CreditUseForm(forms.Form):
    credit = forms.ModelChoiceField(queryset=PaymentResolution.objects.none())
    amount = forms.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0.01"))
    request_key = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4)

    def __init__(self, *args, credits, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["credit"].queryset = credits
        self.fields["credit"].label = t("cancel_customer_credit", "Customer credit")
        self.fields["credit"].label_from_instance = lambda entry: f"{entry.payment.receipt_number} — {entry.available_amount:.2f} LYD"
        self.fields["amount"].label = t("label_payment_amount", "Amount (LYD)")
        for name, field in self.fields.items():
            field.widget.attrs["id"] = f"credit-use-{name}"
        set_field_attrs(self)
        build_grid_helper(self, [("credit",), ("amount",), ("request_key",)])
