"""DjangoLux Options-page registrations for the Products layout.

Auto-imported at startup by dlux's option autodiscovery (`<app>.dlux_options`).

Two surfaces:
  * A per-user picker **card** (`register_card`) — every user who can view
    products chooses their own layout; persisted to their profile preferences.
  * A section of the superuser **CRM options** tile (`common.dlux_options`) that
    sets the shop-wide *default* layout, saved to
    `SystemSettings.extra_config['app']['switch_pos.products_layout']`. The
    per-user pick overrides it; otherwise everyone gets this default.
"""
from dlux.options import register_app_settings, register_card

from common.dlux_options import CRM_OPTIONS_GROUP
from common.i18n import lazy_t

from .product_layouts import (
    PRODUCTS_LAYOUT_DEFAULT_FIELD, PRODUCTS_LAYOUT_NS, get_products_layout,
)

# The selector widget ships with dlux >= 1.4.4; the card falls back to the plain
# button toggle template when it is absent.
try:
    from dlux.widgets import DluxChoiceSelectorWidget
except ImportError:  # pragma: no cover - depends on runtime dlux version
    DluxChoiceSelectorWidget = None


LAYOUT_ICONS = {"table": "bi-table", "grid": "bi-grid-3x3-gap", "light": "bi-list-ul"}


def _layout_choices():
    return [
        ("table", lazy_t("products_layout_table", "Table")),
        ("grid", lazy_t("products_layout_grid", "Grid")),
        ("light", lazy_t("products_layout_light", "Light")),
    ]


def _layout_option_meta():
    return {value: {"icon": icon} for value, icon in LAYOUT_ICONS.items()}


def _title(request):
    return lazy_t("options_products_layout", "Products layout")


def _context(request):
    current = get_products_layout(request)
    selector_html = None
    if DluxChoiceSelectorWidget is not None:
        widget = DluxChoiceSelectorWidget(variant="toggle", option_meta=_layout_option_meta())
        widget.choices = _layout_choices()
        selector_html = widget.render(
            "products_layout", current, attrs={"id": "id_products_layout"}
        )
    return {
        "products_layout": current,
        "products_layout_ns": PRODUCTS_LAYOUT_NS,
        "products_layout_selector_html": selector_html,
    }


register_card(
    id="switch_pos.products_layout",
    title=_title,
    template_name="catalog/options/products_layout_card.html",
    icon="bi-grid-3x3-gap",
    order=50,
    permission="catalog.view_product",
    context_builder=_context,
)


register_app_settings(
    namespace=PRODUCTS_LAYOUT_NS,
    group=CRM_OPTIONS_GROUP,
    title=lazy_t("options_products_layout", "Products layout"),
    description=lazy_t(
        "options_products_layout_default_desc",
        "The shop-wide default Products view. Each user can still override it for themselves.",
    ),
    order=10,
    fields=[
        {
            "name": PRODUCTS_LAYOUT_DEFAULT_FIELD,
            "type": "choice",
            "control": "selector",
            "variant": "toggle",
            "css_class": "col-12",
            "label": lazy_t("options_products_layout_default", "Default products layout"),
            "choices": _layout_choices(),
            "option_meta": _layout_option_meta(),
            "default": "table",
        },
    ],
    defaults={PRODUCTS_LAYOUT_DEFAULT_FIELD: "table"},
)
