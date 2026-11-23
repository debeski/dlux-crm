"""Per-user Products list layout preference.

The choice lives in the user's DjangoLux profile preferences
(`Profile.preferences['app']['sales_crm.products_layout']`) — the same
reserved app-namespace store the workspace dashboard uses — so every user
picks their own product view. It is read server-side here to decide which
template/table `ProductListView` renders, and written client-side via the
staff-prefixed app-preference URL exposed by Django URL reversing (options card
+ inline toggle).
"""

PRODUCTS_LAYOUT_NS = "sales_crm.products_layout"
#: Field name inside the global admin-default settings blob (extra_config).
PRODUCTS_LAYOUT_DEFAULT_FIELD = "default_layout"

PRODUCTS_LAYOUT_TABLE = "table"
PRODUCTS_LAYOUT_GRID = "grid"
PRODUCTS_LAYOUT_LIGHT = "light"

PRODUCTS_LAYOUTS = (PRODUCTS_LAYOUT_TABLE, PRODUCTS_LAYOUT_GRID, PRODUCTS_LAYOUT_LIGHT)
#: Hard fallback when neither a per-user override nor a global admin default is set.
DEFAULT_PRODUCTS_LAYOUT = PRODUCTS_LAYOUT_TABLE


def get_default_products_layout():
    """The global admin default layout (superuser-set), else ``table``.

    Read from ``SystemSettings.extra_config['app'][PRODUCTS_LAYOUT_NS]['default_layout']``
    via dlux's ``get_app_system_config`` (dlux >= 1.4). On an older dlux — where
    that helper/store doesn't exist — this degrades to the table default.
    """
    try:
        from dlux.utils import get_app_system_config
        cfg = get_app_system_config(PRODUCTS_LAYOUT_NS, None)
    except Exception:
        return DEFAULT_PRODUCTS_LAYOUT
    value = cfg.get(PRODUCTS_LAYOUT_DEFAULT_FIELD) if isinstance(cfg, dict) else None
    return value if value in PRODUCTS_LAYOUTS else DEFAULT_PRODUCTS_LAYOUT


def get_products_layout(request):
    """Effective product layout: **per-user override → global admin default → table**.

    The per-user override is ``Profile.preferences['app'][PRODUCTS_LAYOUT_NS]``
    (a scalar). It is read defensively — a missing profile, non-dict preferences,
    or an unknown value all fall through to the global admin default
    (:func:`get_default_products_layout`).
    """
    try:
        # `.profile` raises Profile.DoesNotExist (not AttributeError) when absent,
        # and AnonymousUser has no profile at all — treat every miss as "no override".
        prefs = request.user.profile.preferences
    except Exception:
        prefs = None
    app = prefs.get("app") if isinstance(prefs, dict) else None
    user_value = app.get(PRODUCTS_LAYOUT_NS) if isinstance(app, dict) else None
    if user_value in PRODUCTS_LAYOUTS:
        return user_value
    return get_default_products_layout()
