"""The single "CRM options" tile on the dlux Options page.

dlux gives every ``register_app_settings`` call its own tile, and a tile saves
one ``extra_config['app']`` namespace. The CRM's own settings are small, so the
apps register *sections* here instead: one tile shows them all in one modal,
split by dlux-style section headings, while every section still saves to its
own namespace — so the code that reads those settings is unchanged.

Optional enhancements stay a tile of their own: they switch store types on,
not store options.
"""
from django import forms
from django.utils.html import conditional_escape
from django.utils.safestring import mark_safe

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, LayoutObject
from crispy_forms.utils import render_crispy_form

CRM_OPTIONS_NS = "switch_pos.crm_options"

_SECTIONS = {}


def register_crm_section(*, key, namespace, title, form_class=None, fields=None,
                         description="", defaults=None, order=100):
    """Add one section to the CRM options tile.

    ``fields`` takes dlux field specs (as ``register_app_settings`` does, with
    canonical type names); ``form_class`` takes a form with ``to_app_config``.
    """
    if (form_class is None) == (fields is None):
        raise ValueError(f"register_crm_section[{key}]: pass either fields or form_class")
    _SECTIONS[key] = {
        "key": key,
        "namespace": namespace,
        "title": title,
        "description": description,
        "form_class": form_class,
        "fields": tuple(fields) if fields is not None else None,
        "defaults": dict(defaults or {}),
        "order": order,
    }


def crm_sections():
    return sorted(_SECTIONS.values(), key=lambda section: (section["order"], section["key"]))


def _current(section):
    from dlux.utils import get_app_system_config

    return get_app_system_config(section["namespace"], section["defaults"])


def _section_form(section, data, request):
    current = _current(section)
    if section["form_class"] is None:
        from dlux.options import AppSettingsForm

        return AppSettingsForm(
            data=data, definition=section, current_value=current, request=request, prefix=section["key"],
        )
    return section["form_class"](data=data, current_value=current, request=request, prefix=section["key"])


class _SectionBlock(LayoutObject):
    def __init__(self, section, form, first):
        self.section = section
        self.form = form
        self.first = first

    def render(self, form, context, template_pack=None, **kwargs):
        parts = [] if self.first else ["<hr class='my-4'>"]
        parts.append(f"<h6 class='fw-bold my-3'>{conditional_escape(str(self.section['title']))}</h6>")
        if self.section["description"]:
            parts.append(f"<p class='text-muted small mb-3'>{conditional_escape(str(self.section['description']))}</p>")
        parts.append(render_crispy_form(self.form))
        return mark_safe("".join(parts))


class CrmOptionsForm(forms.Form):
    def __init__(self, *args, request=None, **kwargs):
        for name in ("namespace", "settings_definition", "current_value", "initial"):
            kwargs.pop(name, None)
        super().__init__(*args, **kwargs)
        self.request = request
        data = self.data if self.is_bound else None
        self.sections = [(section, _section_form(section, data, request)) for section in crm_sections()]
        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.layout = Layout(*[
            _SectionBlock(section, form, index == 0) for index, (section, form) in enumerate(self.sections)
        ])

    def is_valid(self):
        results = [form.is_valid() for _section, form in self.sections]
        return super().is_valid() and all(results)

    def to_app_config(self, current_value=None):
        from dlux.options import write_app_system_config

        for section, form in self.sections:
            write_app_system_config(section["namespace"], form.to_app_config(_current(section)), request=self.request)
        # The tile's own namespace stores nothing.
        return None
