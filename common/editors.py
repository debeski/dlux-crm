"""A shared editor for multi-line documents.

Generalised from the sales edition's invoice editor. Of its moving parts only
the price rule was ever domain-specific: the picker is a JSON blob rendered
client-side, and the cart is a plain Django inline formset. Everything else —
the atomic save, the formset lifecycle, the deleted-object handling — is
document-shaped rather than invoice-shaped, so it lives here.

Subclasses supply the two forms and override the hooks they need:

``picker_map()``            what the tile grid renders from
``apply_line_defaults()``   per-line values frozen at save time
``sync_counterparty()``     bind/create the party the document addresses
``post_save()``             recalculate totals, assign a number, …
``success_url()``           where to send the browser afterwards
"""
import json

from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.views import View

from dlux.utils import log_user_action


class DocumentEditorView(LoginRequiredMixin, PermissionRequiredMixin, View):
    # A page: an expired session should land on the login form, not a 403.
    raise_exception = False

    #: ModelForm for the document header.
    document_form = None
    #: Inline formset class for its lines.
    item_formset = None
    template_name = None
    #: Form fragment returned to dlux's universal dynamic modal, when the editor
    #: is opened as one. Left unset by a page-only editor.
    partial_template_name = None
    #: Where to send the browser after a successful save, when the document
    #: itself is not needed to build the URL.
    success_url_name = None
    #: Context key the template reads the picker payload from.
    picker_context_key = "picker_map_json"

    # --- hooks ------------------------------------------------------------- #

    def get_object(self):
        """The document being edited, or None when creating one."""
        return None

    def picker_map(self):
        """JSON-ready payload the client renders the picker grid from."""
        return {}

    def form_kwargs(self):
        """Extra kwargs passed to the document form."""
        return {}

    def apply_line_defaults(self, item, document):
        """Freeze per-line values at save time (the invoice editor's price rule)."""

    def apply_document_defaults(self, document):
        """Freeze header values at save time — the invoice editor's rate rule.

        The line-level counterpart of `apply_line_defaults`: a document that
        prices in a second currency has to capture the rate it was written at,
        or reprinting it later silently revalues it.
        """

    def sync_counterparty(self, document, actor):
        """Bind or create the party this document addresses."""

    def post_save(self, document):
        """Runs inside the transaction once lines are written."""

    def extra_context(self, document=None):
        return {}

    def success_url(self, document):
        return reverse(self.success_url_name)

    def on_valid(self, request, document):
        """After a successful save, before redirecting — messages, etc."""

    # --- plumbing ---------------------------------------------------------- #

    def _context(self, form, formset, document=None):
        payload = self.picker_map()
        context = {
            "form": form,
            "formset": formset,
            "document": document,
            "is_edit": document is not None,
            self.picker_context_key: (
                payload if isinstance(payload, str) else json.dumps(payload)
            ),
        }
        context.update(self.extra_context(document))
        return context

    def _is_modal_request(self, request):
        return request.headers.get("X-Requested-With") == "XMLHttpRequest"

    def _render(self, request, context):
        context = {
            **context,
            "editor_url": request.get_full_path(),
            "is_modal": self._is_modal_request(request),
        }
        if context["is_modal"] and self.partial_template_name:
            return JsonResponse({
                "success": False,
                "html": render_to_string(
                    self.partial_template_name, context, request=request,
                ),
            })
        return render(request, self.template_name, context)

    def _save(self, request, form, formset, document=None):
        # Captured before save(): afterwards every instance has a pk, which is
        # why the original editor always logged an UPDATE.
        is_new = document is None or document.pk is None
        with transaction.atomic():
            document = form.save(commit=False)
            self.apply_document_defaults(document)
            self.sync_counterparty(document, request.user)
            document.save()

            formset.instance = document
            for item in formset.save(commit=False):
                self.apply_line_defaults(item, document)
                item.save()
            for item in formset.deleted_objects:
                item.delete()
            formset.save_m2m()

            self.post_save(document)
            log_user_action(request, "CREATE" if is_new else "UPDATE", instance=document)
        return document

    def _build(self, request, document=None, bind=False):
        data = request.POST if bind else None
        form = self.document_form(data, instance=document, **self.form_kwargs())
        formset = self.item_formset(data, instance=document)
        return form, formset

    def get(self, request, *args, **kwargs):
        document = self.get_object()
        redirected = self.check_editable(request, document)
        if redirected is not None:
            return redirected
        form, formset = self._build(request, document)
        return self._render(request, self._context(form, formset, document))

    def post(self, request, *args, **kwargs):
        document = self.get_object()
        redirected = self.check_editable(request, document)
        if redirected is not None:
            return redirected
        form, formset = self._build(request, document, bind=True)
        if form.is_valid() and formset.is_valid():
            document = self._save(request, form, formset, document)
            self.on_valid(request, document)
            if self._is_modal_request(request) and self.partial_template_name:
                return JsonResponse({"success": True, "refresh_parent": True})
            return redirect(self.success_url(document))
        return self._render(request, self._context(form, formset, document))

    def check_editable(self, request, document):
        """Return a response to short-circuit with, or None to carry on.

        A document whose lifecycle has moved past drafting is not editable, and
        both GET and POST have to say so — otherwise the form renders happily
        and the save is refused only on submit.
        """
        return None


def sync_party(document, *, prefix, party_model, queryset=None):
    """Bind a document to the party it names, creating one if it is new.

    A document carries both a FK to the party and a snapshot of its name, phone
    and address — the snapshot is what prints, and it must not change when the
    party record is later edited. Binding therefore runs both ways:

    - Party picked (FK set): fill the document's blank snapshot fields from it.
    - Name typed (no FK): reuse a party of that name if one exists, else create
      one — so every party entered is saved for reuse rather than living only on
      the document that mentioned it.
    - Either way, backfill the party's own blank phone/address from what was
      typed, without clobbering values it already holds.

    ``prefix`` names the document's field group (``customer`` -> ``customer``,
    ``customer_name``, ``customer_phone``, ``customer_address``). ``queryset``
    narrows what counts as an existing party: sales customers are private, so a
    rep matches only within their own book and a new name creates a record owned
    by them.
    """
    name = (getattr(document, f"{prefix}_name", "") or "").strip()
    party = getattr(document, prefix, None) if getattr(document, f"{prefix}_id", None) else None
    if party is None and name:
        source = party_model._default_manager.all() if queryset is None else queryset
        party = source.filter(name__iexact=name).first()
        if party is None:
            party = party_model(name=name)
    if party is None:
        return  # a true walk-in with no name at all

    for attribute in ("name", "phone", "address"):
        field = f"{prefix}_{attribute}"
        setattr(
            document, field,
            getattr(document, field, "") or getattr(party, attribute, "") or "",
        )

    dirty = party.pk is None
    if not party.name and name:
        party.name, dirty = name, True
    for attribute in ("phone", "address"):
        typed = getattr(document, f"{prefix}_{attribute}", "")
        if typed and not getattr(party, attribute, ""):
            setattr(party, attribute, typed)
            dirty = True
    if dirty:
        party.save()
    setattr(document, prefix, party)
