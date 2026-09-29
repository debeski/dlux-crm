import uuid

from django import forms

from common.i18n import t


class PublicContactForm(forms.Form):
    idempotency_key = forms.CharField(widget=forms.HiddenInput)
    source_path = forms.CharField(required=False, widget=forms.HiddenInput)
    company = forms.CharField(required=False, widget=forms.HiddenInput)
    name = forms.CharField(max_length=160)
    email = forms.EmailField()
    phone = forms.CharField(max_length=60, required=False)
    subject = forms.CharField(max_length=180, required=False)
    message = forms.CharField(widget=forms.Textarea(attrs={"rows": 5}))

    def __init__(self, *args, **kwargs):
        source_path = kwargs.pop("source_path", "")
        super().__init__(*args, **kwargs)
        self.fields["idempotency_key"].initial = uuid.uuid4().hex
        self.fields["source_path"].initial = source_path
        self.fields["name"].widget.attrs.update({"autocomplete": "name", "placeholder": t("public_contact_ph_name", "Your name")})
        self.fields["email"].widget.attrs.update({"autocomplete": "email", "placeholder": "you@example.com"})
        self.fields["phone"].widget.attrs.update({"autocomplete": "tel", "placeholder": t("public_contact_ph_phone", "Optional")})
        self.fields["subject"].widget.attrs.update({"placeholder": t("public_contact_ph_subject", "What can we help with?")})
        self.fields["message"].widget.attrs.update({"placeholder": t("public_contact_ph_message", "Tell us what you need installed, supplied, or checked.")})

    def clean_idempotency_key(self):
        key = (self.cleaned_data["idempotency_key"] or "").strip()
        if len(key) < 16:
            raise forms.ValidationError(t("public_contact_invalid_key", "Invalid submission key."))
        return key[:64]
