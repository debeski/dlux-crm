"""Shared row-action helpers for project tables.

dlux is modal-first, and a context-menu entry opens a modal by dispatching
``dlux:dynamic_modal:open`` with the URL it should load — the same event the
"Add" button uses. That is self-contained: it needs no page-level listener and
no ordering against dlux's own ``dlux:record:*`` fallback, which lives on
``window`` and navigates to ``/{app}/{id}/edit/`` routes this project does not
have.

The generic ``dlux:record:view`` / ``dlux:record:edit`` actions depend on that
fallback being intercepted first — which is exactly what ``scoped_crud.js`` does.
Emitting the modal event directly removes the dependency entirely; ``delete``
stays on the record event, because the shim turns it into a POST against the
modal-delete route.
"""
from django.urls import reverse

from common.i18n import t


def modal_url(model, pk, *, view=False):
    """URL of the project's form-only dynamic modal for one record."""
    opts = model._meta
    url = reverse("scoped_modal_manager", args=[opts.app_label, opts.object_name, pk])
    return f"{url}?action=view" if view else url


def modal_action(label, icon, url, title="", permissions=None, dblclick=False):
    """A context-menu entry that opens a dlux dynamic modal.

    ``dblclick=True`` also makes it the row's double-click action — dlux's
    context menu runs the single entry marked that way, which is how its own
    tables promote View.
    """
    action = {
        "label": label,
        "icon": icon,
        "type": "event",
        "event": "dlux:dynamic_modal:open",
        "data": {"url": url, "title": title or label},
    }
    if permissions:
        action["permissions"] = list(permissions)
    if dblclick:
        action["dblclick"] = True
    return action


def link_action(label, icon, url, permissions=None, new_tab=False):
    """A context-menu entry that navigates.

    ``new_tab=True`` opens it in a new tab instead of leaving the list — dlux's
    context menu honours ``target: "_blank"``. Wanted for anything that produces
    a document rather than a screen: a printed invoice is read or saved and then
    finished with, and navigating the list away to reach it means going back for
    the next row.
    """
    action = {"label": label, "icon": icon, "type": "url", "url": url}
    if new_tab:
        action["target"] = "_blank"
    if permissions:
        action["permissions"] = list(permissions)
    return action


class ModalRowActionsMixin:
    """View and edit a record in a modal, without the record-event fallback.

    ``row_delete_action`` is True by default here: unlike the gov edition, most
    of this project's reference data is genuinely deletable through the same
    guarded modal route the Add button uses. Set it False on a table whose rows
    are cancelled or voided rather than removed — an issued invoice, a posted
    ledger entry — so the ledger stays readable.
    """

    row_delete_action = True

    def _on_dlux_sections_manager(self):
        """True while this table is drawn on dlux's Section Management page."""
        match = getattr(getattr(self, "request", None), "resolver_match", None)
        return getattr(match, "url_name", "") == "manage_sections"

    def get_dlux_row_actions(self, record, base_actions):
        # That page edits a record in its own expanding form, driven by the
        # `dlux:record:*` events its context-menu script listens for. Opening a
        # modal there would talk over the surface the page is built around.
        if self._on_dlux_sections_manager():
            return base_actions

        model = self._meta.model
        opts = model._meta
        name = str(record)
        # Inside a stacked manager modal the record lives on that manager's own
        # route, so the row keeps the reader in the modal they opened.
        manager_url = getattr(self, "dlux_modal_manager_url", "")

        def record_url(view=False):
            if not manager_url:
                return modal_url(model, record.pk, view=view)
            url = f"{manager_url}?id={record.pk}"
            return f"{url}&action=view" if view else url

        actions = [
            modal_action(
                t("ui_view", "View"), "bi bi-eye",
                record_url(view=True), name, dblclick=True,
            ),
            {"type": "divider"},
            modal_action(
                t("ui_edit", "Edit"), "bi bi-pencil",
                record_url(), name,
                permissions=[f"{opts.app_label}.change_{opts.model_name}"],
            ),
        ]
        if self.row_delete_action:
            # Left to dlux's own delete event, which the project's scoped_crud
            # shim turns into a POST against the modal-delete route.
            actions.extend(
                action for action in base_actions
                if action.get("event") == "dlux:record:delete"
            )
        if getattr(self, "dlux_section_actions", False):
            for action in actions:
                if action.get("permissions"):
                    action["section_action"] = True
        return actions
