from django import forms
from django.contrib.auth import get_user_model

from dlux.translations import get_strings
from dlux.utils import set_field_attrs

from common.forms import (
    apply_dlux_file_widgets, build_grid_helper, translate_choice_fields,
    translate_help_text,
)

from .models import CashDeposit, ExchangeRate, Expense, ExpenseCategory, StaffAccount, StaffLedgerEntry

User = get_user_model()


class ExchangeRateForm(forms.ModelForm):
    # Reload the parent list page after a successful dynamic-modal save.
    refresh_parent = True

    class Meta:
        model = ExchangeRate
        fields = ["rate", "source", "note"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        set_field_attrs(self)
        translate_choice_fields(self)
        translate_help_text(self)
        build_grid_helper(self, [("rate", "source"), ("note",)])


class CashDepositForm(forms.ModelForm):
    refresh_parent = True

    class Meta:
        model = CashDeposit
        # status / confirmation are driven by privileged actions, never the form.
        fields = ["amount", "method", "deposited_at", "reference", "notes"]
        widgets = {"deposited_at": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # When this deposit carries invoice payments its amount is the auto-summed
        # batch total — lock the field so it isn't hand-edited out of sync.
        if self.instance.pk and self.instance.payments.exists():
            self.fields["amount"].disabled = True
            self.fields["amount"].help_text = get_strings().get(
                "help_deposit_amount_auto", "Auto-calculated from linked invoice payments."
            )
        set_field_attrs(self)
        translate_choice_fields(self)
        # Runs after the auto-sum note above; there is no help_cashdeposit_amount
        # key, so that per-instance note is preserved.
        translate_help_text(self)
        build_grid_helper(self, [("amount", "method"), ("deposited_at", "reference"), ("notes",)])


class ExpenseCategoryForm(forms.ModelForm):
    refresh_parent = True

    class Meta:
        model = ExpenseCategory
        fields = ["name", "description", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        set_field_attrs(self)
        translate_help_text(self)
        build_grid_helper(self, [("name", "is_active"), ("description",)])


class ExpenseForm(forms.ModelForm):
    refresh_parent = True

    class Meta:
        model = Expense
        fields = [
            "category", "amount_lyd", "expense_date", "method", "paid_by",
            "reference", "attachment", "notes",
        ]
        widgets = {"expense_date": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = ExpenseCategory.objects.filter(is_active=True).order_by("name")
        self.fields["paid_by"].required = False
        self.fields["paid_by"].queryset = User.objects.filter(is_active=True).order_by("first_name", "username")
        set_field_attrs(self)
        translate_choice_fields(self)
        translate_help_text(self)
        apply_dlux_file_widgets(
            self,
            accept={"attachment": "image/*,application/pdf"},
            show_scan=("attachment",),
        )
        build_grid_helper(self, [
            ("category", "amount_lyd"),
            ("expense_date", "method"),
            ("paid_by", "reference"),
            ("attachment",),
            ("notes",),
        ])


class StaffAccountForm(forms.ModelForm):
    refresh_parent = True

    class Meta:
        model = StaffAccount
        fields = ["user", "is_active", "notes"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        used = StaffAccount.objects.exclude(pk=self.instance.pk).values_list("user_id", flat=True)
        self.fields["user"].queryset = User.objects.filter(is_active=True).exclude(pk__in=used).order_by("first_name", "username")
        set_field_attrs(self)
        translate_help_text(self)
        build_grid_helper(self, [("user", "is_active"), ("notes",)])


class StaffLedgerEntryForm(forms.ModelForm):
    refresh_parent = True

    class Meta:
        model = StaffLedgerEntry
        fields = [
            "account", "entry_type", "amount_lyd", "entry_date", "reference",
            "requires_user_confirmation", "notes",
        ]
        widgets = {"entry_date": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["account"].queryset = StaffAccount.objects.filter(is_active=True).select_related("user").order_by("user__username")
        set_field_attrs(self)
        translate_choice_fields(self)
        translate_help_text(self)
        build_grid_helper(self, [
            ("account", "entry_type"),
            ("amount_lyd", "entry_date"),
            ("reference", "requires_user_confirmation"),
            ("notes",),
        ])
