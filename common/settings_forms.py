"""Dependent settings the way dlux's own settings steps do them.

Settings that only matter while a master toggle is on stay visible but greyed
out, with a tooltip saying which toggle unlocks them. While the master is off
the fields are disabled server-side too, so Django keeps their stored values
instead of saving the blanks a browser sends for disabled inputs.
``common/js/dependent_settings.js`` follows the master live in the modal.
"""
from crispy_forms.layout import Div

from .i18n import t


def master_on(form, master):
    if form.is_bound:
        field = form.fields[master]
        return bool(field.widget.value_from_datadict(form.data, form.files, form.add_prefix(master)))
    return bool(form.initial.get(master, form.fields[master].initial))


def lock_dependents(form, master, names):
    """Disable ``names`` while ``master`` is off. Call before building the layout."""
    if not master_on(form, master):
        for name in names:
            form.fields[name].disabled = True


def dependent_block(form, master, *items, css_class=""):
    bound = form[master]
    reason = t("settings_dependent_disabled", "Turn on “{name}” to change these settings.").replace(
        "{name}", str(bound.label),
    )
    on = master_on(form, master)
    attrs = {"data-settings-depends-on": bound.html_name, "data-settings-lock-reason": reason}
    if not on:
        attrs.update({"data-dlux-tooltip": reason, "aria-disabled": "true"})
    classes = "dlux-dependent-settings" + ("" if on else " is-disabled")
    return Div(*items, css_class=f"{classes} {css_class}".strip(), **attrs)
