"""
Row-level (per-employee) visibility on top of dlux's model-level permissions.

Django permissions are model-level ("can view invoices"). This module adds the
*which rows* layer: a regular employee sees only records they own, while a
manager (or superuser) with the model's ``view_all_<model>`` permission sees
everything.

Ownership is declared per model by an ``OWNER_FIELDS`` class attribute — a tuple
of ORM lookups that point at a user (e.g. ``("salesperson", "created_by")`` or
``("invoice__salesperson",)``). A model without ``OWNER_FIELDS`` is treated as
shared (the product catalog, exchange rates, …) and never row-filtered.

Filtering is applied at the READ choke points only (list pages, the dynamic
modal edit/view/delete lookup, invoice detail/report). It is deliberately NOT a
model manager: whether you may see a ``Payment`` depends on context — its own
standalone list is owner-filtered, but the payments *of an invoice you already
own* must all show, regardless of who keyed them in.
"""
from django.db.models import Q


def view_all_perm(model):
    """The permission codename that lets a user see every row of ``model``."""
    opts = model._meta
    return f"{opts.app_label}.view_all_{opts.model_name}"


def user_can_view_all(user, model):
    """True if ``user`` bypasses row-filtering for ``model`` (manager/admin)."""
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True
    return user.has_perm(view_all_perm(model))


def apply_ownership(queryset, user):
    """Restrict ``queryset`` to rows ``user`` owns, unless the model is shared or
    the user may view all. Safe to call on any queryset — a model without
    ``OWNER_FIELDS`` is returned unchanged."""
    model = queryset.model
    owner_fields = getattr(model, "OWNER_FIELDS", None)
    if not owner_fields:
        return queryset  # shared model — no row filtering
    if user_can_view_all(user, model):
        return queryset
    if user is None or not getattr(user, "is_authenticated", False):
        return queryset.none()
    predicate = Q()
    for lookup in owner_fields:
        predicate |= Q(**{lookup: user})
    # OR across related lookups can multiply rows via joins — collapse them.
    return queryset.filter(predicate).distinct()
