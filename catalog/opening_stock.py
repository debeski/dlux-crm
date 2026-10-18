"""Persistent opening-stock work in progress, isolated by store scope."""
import json

from django.core.exceptions import PermissionDenied, ValidationError
from dlux.utils import get_user_scope, is_scope_enabled

from common.i18n import t
from .forms import OpeningStockLineForm, OpeningStockLineFormSet
from .models import OpeningStockDraft
from .opening_stock_import import MAX_IMPORT_BYTES, MAX_IMPORT_ROWS


def opening_scope(user):
    if not is_scope_enabled():
        return None
    scope = get_user_scope(user)
    if scope is None and not getattr(user, "is_superuser", False):
        raise PermissionDenied
    return scope


def draft_for(user):
    return OpeningStockDraft.objects.filter(scope=opening_scope(user)).first()


def locked_draft(user):
    scope = opening_scope(user)
    draft, _ = OpeningStockDraft.objects.get_or_create(scope=scope)
    return OpeningStockDraft.objects.select_for_update().get(pk=draft.pk)


def draft_rows(post, user):
    try:
        count = int(post.get("form-TOTAL_FORMS", ""))
    except (TypeError, ValueError):
        count = -1
    if not 0 <= count <= MAX_IMPORT_ROWS * 2:
        raise ValidationError(t("opening_row_limit"))
    fields = OpeningStockLineForm(user=user).fields
    rows = []
    for index in range(count):
        prefix = f"form-{index}-"
        if post.get(prefix + "DELETE"):
            continue
        row = {name: post.getlist(prefix + name) if name == "machine_models" else post.get(prefix + name, "") for name in fields}
        text_fields = ("name", "alias", "category", "barcode", "color", "size", "product", "machine_models", "price_lyd_override")
        number_fields = ("cost_usd", "markup_percent", "price_usd", "quantity")
        if not any(row.get(field) for field in text_fields) and all(row.get(field) in ("", "0", "0.0", "0.00") for field in number_fields) and row.get("unit") in ("", "piece"):
            continue
        rows.append(row)
    if len(rows) > MAX_IMPORT_ROWS:
        raise ValidationError(t("opening_row_limit"))
    if len(json.dumps(rows).encode()) > MAX_IMPORT_BYTES:
        raise ValidationError(t("opening_draft_too_large"))
    return rows


def resumed_formset(draft, user):
    return OpeningStockLineFormSet(initial=draft.rows if draft else [], form_kwargs={"user": user, "opening_only": True})
