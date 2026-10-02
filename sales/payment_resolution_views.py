from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.views import View

from dlux.utils import log_user_action
from common.access import apply_ownership
from common.i18n import t
from .models import Customer, Invoice, PaymentResolution
from .payment_resolution_forms import CancellationForm, CreditUseForm
from .services import apply_customer_credit, cancel_invoice


def visible_credits(invoice, user):
    if not invoice.customer_id or not apply_ownership(Customer.objects.filter(pk=invoice.customer_id), user).exists():
        return PaymentResolution.objects.none()
    return PaymentResolution.objects.filter(
        customer_id=invoice.customer_id, action="credit",
        payment__invoice__in=apply_ownership(Invoice.objects.all(), user),
    ).select_related("payment")


class InvoiceMoneyModal(LoginRequiredMixin, PermissionRequiredMixin, View):
    raise_exception = True

    def invoice(self):
        return get_object_or_404(apply_ownership(Invoice.objects.all(), self.request.user), pk=self.kwargs["pk"])

    def response(self, invoice, form):
        context = {
            "invoice": invoice, "form": form, "title": self.title,
            "submit_label": self.submit_label,
            "editor_url": self.request.path,
            "is_cancel": isinstance(form, CancellationForm),
        }
        if self.request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse({"success": False, "html": render_to_string("sales/invoice_money_modal.html", context, request=self.request)})
        return render(self.request, "sales/invoice_money_page.html", context)

    def get(self, request, pk):
        invoice = self.invoice()
        return self.response(invoice, self.form(invoice))

    def post(self, request, pk):
        invoice = self.invoice()
        form = self.form(invoice, request.POST)
        if form.is_valid():
            try:
                self.process(invoice, form.cleaned_data)
            except ValidationError as exc:
                form.add_error(None, exc)
            else:
                if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                    return JsonResponse({"success": True, "refresh_parent": True})
                return redirect(reverse("sales:invoice_detail", args=[invoice.pk]))
        return self.response(invoice, form)


class InvoiceCancellationView(InvoiceMoneyModal):
    permission_required = "sales.cancel_invoice"

    @property
    def title(self):
        return t("cancel_title", "Cancel invoice / resolve payments")

    @property
    def submit_label(self):
        return t("cancel_confirm_action", "Confirm cancellation / settlement")

    def form(self, invoice, data=None):
        return CancellationForm(data, invoice=invoice)

    def process(self, invoice, data):
        cancel_invoice(invoice, self.request.user, **data)
        log_user_action(self.request, "CANCEL", instance=invoice)


class CustomerCreditUseView(InvoiceMoneyModal):
    permission_required = "sales.add_payment"

    @property
    def title(self):
        return t("cancel_apply_credit", "Apply customer credit")

    @property
    def submit_label(self):
        return t("cancel_apply_credit", "Apply customer credit")

    def form(self, invoice, data=None):
        return CreditUseForm(data, credits=visible_credits(invoice, self.request.user))

    def process(self, invoice, data):
        apply_customer_credit(invoice, user=self.request.user, **data)
        log_user_action(self.request, "CREDIT_PAYMENT", instance=invoice)
