"""Translated navbar trails for routes the sidebar builder never sees.

DLux labels a breadcrumb from its sidebar catalog; a route excluded from the
sidebar falls back to its humanized URL name ("Make List") in every language.
A `dlux_navbar_crumbs` context entry replaces that trail with DLUX_STRINGS keys.
"""

HUB = {"url_name": "automotive:hub", "label_key": "automotive_hub"}

ROUTE_CRUMBS = {
    "automotive:type_list": [HUB, {"label_key": "models_equipmenttype"}],
    "automotive:make_list": [HUB, {"label_key": "page_title_automotive_make_list"}],
    "automotive:model_list": [HUB, {"label_key": "page_title_automotive_model_list"}],
    "automotive:generation_list": [HUB, {"label_key": "page_title_automotive_generation_list"}],
    "automotive:engine_list": [HUB, {"label_key": "page_title_automotive_engine_list"}],
    "automotive:trim_list": [HUB, {"label_key": "page_title_automotive_trim_list"}],
    "automotive:product_fitments": [
        {"url_name": "catalog:product_list", "label_key": "page_products"},
        {"label_key": "page_title_automotive_product_fitments"},
    ],
    "catalog:purchase_invoice_create": [
        {"url_name": "catalog:purchase_invoice_list", "label_key": "page_purchase_invoices"},
        {"label_key": "page_title_catalog_purchase_invoice_create"},
    ],
    "catalog:opening_stock": [
        {"url_name": "catalog:stock_movement_list", "label_key": "page_stock_movements"},
        {"label_key": "page_title_catalog_opening_stock"},
    ],
    "catalog:opening_stock_detail": [
        {"url_name": "catalog:stock_movement_list", "label_key": "page_stock_movements"},
        {"label_key": "page_title_catalog_opening_stock_detail"},
    ],
    "catalog:stock_take_create": [
        {"url_name": "catalog:stock_take_list", "label_key": "page_stock_takes"},
        {"label_key": "page_title_catalog_stock_take_create"},
    ],
}


def navbar_crumbs(request):
    match = getattr(request, "resolver_match", None)
    crumbs = ROUTE_CRUMBS.get(getattr(match, "view_name", "") or "")
    return {"dlux_navbar_crumbs": crumbs} if crumbs else {}


def pricing_currency(request):
    """``PRICING_CURRENCY``: the code (USD/EUR) catalog prices are kept in.

    Documents show their own ``currency`` instead; this is for everything else.
    """
    from finance.currency import pricing_currency as current

    return {"PRICING_CURRENCY": current()}


def crm_context(request):
    """Apply enhancement visibility to discovered and manually saved navigation."""
    from dlux.context_processors import dlux_context
    from automotive.settings import get_optional_enhancements_config
    from django.urls import reverse

    context = dict(dlux_context(request))
    config = get_optional_enhancements_config()
    disabled = {name: reverse(f"{name}:hub") for name in ("automotive", "machinery") if not config.get(name, {}).get("enabled", False)}

    def hidden(item):
        name = str(item.get("url_name") or item.get("id") or "")
        url = str(item.get("url") or "")
        return any(name.startswith(f"{app}:") or url.startswith(prefix) for app, prefix in disabled.items())

    def visible(items):
        result = []
        for original in items or []:
            item = dict(original)
            if item.get("kind") == "group":
                item["items"] = visible(item.get("items"))
                if not item["items"]:
                    continue
                if hidden(item):
                    item["url"] = "#"
                    item["url_name"] = None
            elif hidden(item):
                continue
            result.append(item)
        return result

    for key in ("sidebar_entries", "sidebar_tree_state", "sidebar_auto_items", "sidebar_extra_groups"):
        context[key] = visible(context.get(key))
    context["sidebar"] = {**context.get("sidebar", {}), "entries": context["sidebar_entries"], "auto_items": context["sidebar_auto_items"], "extra_groups": context["sidebar_extra_groups"]}
    return context
