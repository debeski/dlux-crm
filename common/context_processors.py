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
