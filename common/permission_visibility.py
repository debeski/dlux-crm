"""Keep the permission editors to the features that are switched on.

Vehicles (automotive), Machinery, POS and the public site are optional. While one is off, its
permissions leave the group/user permission editors; DjangoLux keeps the grants
on save, so switching the feature back on shows them unchanged.
"""
from django.db.models import Q

POS_PERMISSIONS = Q(content_type__app_label="sales", content_type__model="possale") | Q(
    content_type__app_label="sales", codename__in=["use_pos", "pos_unlimited_discount"]
)


def hidden_feature_permissions():
    from automotive.settings import automotive_enabled
    from machinery.settings import machinery_enabled
    from public_catalog.settings import public_site_enabled
    from sales.pos_settings import get_pos_config

    hidden = []
    if not automotive_enabled():
        hidden.append(Q(content_type__app_label="automotive"))
    if not machinery_enabled():
        hidden.append(Q(content_type__app_label="machinery"))
    if not get_pos_config()["enabled"]:
        hidden.append(POS_PERMISSIONS)
    if not public_site_enabled():
        hidden.append(Q(content_type__app_label="public_catalog"))
    if not hidden:
        return None
    condition = hidden[0]
    for extra in hidden[1:]:
        condition |= extra
    return condition


def register():
    try:
        from dlux.access import register_permission_visibility_filter
    except ImportError:  # DjangoLux without permission visibility filters
        return
    register_permission_visibility_filter(hidden_feature_permissions)
