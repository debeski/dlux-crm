from collections import defaultdict
from urllib.parse import urlencode

from django.core.exceptions import FieldDoesNotExist
from django.db.models import Count, Q
from django.urls import reverse

from dlux.utils import get_user_scope, is_scope_enabled

from catalog.models import Category, Product
from common.i18n import t

from .models import ProductFitment, VehicleEngine, VehicleGeneration, VehicleTrim


def _integer(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _url(params):
    clean = {key: value for key, value in params.items() if value not in (None, "")}
    base = reverse("automotive:browse")
    return f"{base}?{urlencode(clean)}" if clean else base


def _count_products(rows, field, value, broad=None):
    return len({
        row["product_id"]
        for row in rows
        if row[field] == value or row[field] == broad
    })


class VehicleBrowser:
    """Build one query-parameter-driven vehicle path without duplicating Products."""

    row_fields = (
        "product_id",
        "product__category_id",
        "year_from",
        "year_to",
        "generation_id",
        "engine_id",
        "trim_id",
        "transmission",
        "position",
    )

    def __init__(self, request, config):
        self.request = request
        self.user = request.user
        self.params = request.GET
        self.criteria = config["criteria"]
        self.base_params = {}
        self.breadcrumbs = []
        self.scope_enabled = is_scope_enabled()
        self.user_scope = (
            get_user_scope(self.user)
            if self.scope_enabled and not getattr(self.user, "is_superuser", False)
            else None
        )

        self.products = self._queryset(Product).filter(is_active=True)
        self.fitments = self._queryset(ProductFitment).filter(
            product__is_active=True,
            vehicle_model__is_active=True,
            vehicle_model__make__is_active=True,
        )
        if self.criteria["generation_chassis"]:
            self.fitments = self.fitments.filter(
                Q(generation__isnull=True) | Q(generation__is_active=True),
            )
        if self.criteria["engine"]:
            self.fitments = self.fitments.filter(
                Q(engine__isnull=True) | Q(engine__is_active=True),
            )
        if self.criteria["trim"]:
            self.fitments = self.fitments.filter(
                Q(trim__isnull=True) | Q(trim__is_active=True),
            )

    def _queryset(self, model):
        """Apply the browser's soft-delete and scope policy once per request."""
        queryset = model.all_objects.filter(deleted_at__isnull=True)
        if not self.scope_enabled or getattr(self.user, "is_superuser", False):
            return queryset
        try:
            model._meta.get_field("scope")
        except FieldDoesNotExist:
            return queryset
        if self.user_scope is None:
            return queryset.none()
        return queryset.filter(scope=self.user_scope)

    def _options(self, rows, field, objects, label, param_name, broad=None):
        identifiers = {row[field] for row in rows if row[field] not in (None, "")}
        options = []
        for identifier in sorted(identifiers, key=lambda value: str(value)):
            obj = objects.get(identifier)
            if obj is None:
                continue
            params = {**self.base_params, param_name: identifier}
            options.append({
                "id": identifier,
                "label": label(obj),
                "count": _count_products(rows, field, identifier, broad=broad),
                "url": _url(params),
            })
        return options

    def _selected_option(self, options, param_name):
        requested = self.params.get(param_name)
        requested_id = _integer(requested) if requested is not None else None
        for option in options:
            if str(option["id"]) == str(requested_id if requested_id is not None else requested):
                option["selected"] = True
                self.base_params[param_name] = option["id"]
                self.breadcrumbs.append({"label": option["label"], "url": option["url"]})
                return option["id"]
        return None

    def _relational_step(self, rows, *, field, model, param_name, label, broad=None):
        identifiers = {row[field] for row in rows if row[field] not in (None, "")}
        objects = {
            obj.pk: obj
            for obj in self._queryset(model).filter(pk__in=identifiers, is_active=True)
        }
        options = self._options(rows, field, objects, label, param_name, broad=broad)
        selected = self._selected_option(options, param_name)
        if selected is not None:
            rows = [row for row in rows if row[field] in (selected, broad)]
        return rows, options, selected

    def _choice_step(self, rows, *, field, choices, param_name, broad=""):
        objects = {
            value: t(f"{param_name}_{value}", fallback)
            for value, fallback in choices
            if value
        }
        options = self._options(rows, field, objects, lambda value: value, param_name, broad=broad)
        selected = self._selected_option(options, param_name)
        if selected is not None:
            rows = [row for row in rows if row[field] in (selected, broad)]
        return rows, options, selected

    def _direct_search(self, query):
        queryset = self.products.filter(
            Q(name__icontains=query)
            | Q(sku__icontains=query)
            | Q(barcode__icontains=query)
        ).select_related("category", "image_asset").order_by("name")
        count = queryset.count()
        return {
            "search_query": query,
            "products": list(queryset[:100]),
            "product_count": count,
            "show_results": True,
            "result_limited": count > 100,
            "change_vehicle_url": reverse("automotive:browse"),
        }

    def build(self):
        query = (self.params.get("q") or "").strip()
        if query:
            return self._direct_search(query)

        context = {
            "search_query": "",
            "products": [],
            "product_count": 0,
            "show_results": False,
            "change_vehicle_url": reverse("automotive:browse"),
        }

        make_rows = self.fitments.values(
            "vehicle_model__make_id", "vehicle_model__make__name",
        ).annotate(product_count=Count("product_id", distinct=True)).order_by("vehicle_model__make__name")
        make_options = [
            {
                "id": row["vehicle_model__make_id"],
                "label": row["vehicle_model__make__name"],
                "count": row["product_count"],
                "url": _url({"make": row["vehicle_model__make_id"]}),
            }
            for row in make_rows
        ]
        make_id = self._selected_option(make_options, "make")
        context["make_options"] = make_options
        if make_id is None:
            context["next_step"] = "make"
            context["breadcrumbs"] = self.breadcrumbs
            return context

        model_rows = self.fitments.filter(vehicle_model__make_id=make_id).values(
            "vehicle_model_id", "vehicle_model__name",
        ).annotate(product_count=Count("product_id", distinct=True)).order_by("vehicle_model__name")
        model_options = [
            {
                "id": row["vehicle_model_id"],
                "label": row["vehicle_model__name"],
                "count": row["product_count"],
                "url": _url({"make": make_id, "model": row["vehicle_model_id"]}),
            }
            for row in model_rows
        ]
        model_id = self._selected_option(model_options, "model")
        context["model_options"] = model_options
        if model_id is None:
            context["next_step"] = "model"
            context["breadcrumbs"] = self.breadcrumbs
            return context

        rows = list(self.fitments.filter(vehicle_model_id=model_id).values(*self.row_fields))
        year_products = defaultdict(set)
        for row in rows:
            for year in range(row["year_from"], row["year_to"] + 1):
                year_products[year].add(row["product_id"])
        year_options = [
            {
                "id": year,
                "label": str(year),
                "count": len(product_ids),
                "url": _url({"make": make_id, "model": model_id, "year": year}),
            }
            for year, product_ids in sorted(year_products.items(), reverse=True)
        ]
        year = self._selected_option(year_options, "year")
        context["year_options"] = year_options
        if year is None:
            context["next_step"] = "year"
            context["breadcrumbs"] = self.breadcrumbs
            return context
        rows = [row for row in rows if row["year_from"] <= year <= row["year_to"]]

        if self.criteria["generation_chassis"]:
            def generation_label(item):
                return f"{item.name} ({item.chassis_code})" if item.chassis_code else item.name

            rows, options, selected = self._relational_step(
                rows,
                field="generation_id",
                model=VehicleGeneration,
                param_name="generation",
                label=generation_label,
                broad=None,
            )
            context["generation_options"] = options if len(options) > 1 or selected else []

        if self.criteria["engine"]:
            def engine_label(item):
                bits = [item.display_name]
                if item.engine_code:
                    bits.append(item.engine_code)
                if item.displacement is not None:
                    bits.append(f"{item.displacement:g}L")
                if self.criteria["fuel_type"] and item.fuel_type:
                    bits.append(t(f"fuel_{item.fuel_type}", item.get_fuel_type_display()))
                return " · ".join(bits)

            rows, options, selected = self._relational_step(
                rows,
                field="engine_id",
                model=VehicleEngine,
                param_name="engine",
                label=engine_label,
                broad=None,
            )
            context["engine_options"] = options if len(options) > 1 or selected else []

        if self.criteria["trim"]:
            rows, options, selected = self._relational_step(
                rows,
                field="trim_id",
                model=VehicleTrim,
                param_name="trim",
                label=lambda item: item.name,
                broad=None,
            )
            context["trim_options"] = options if len(options) > 1 or selected else []

        if self.criteria["transmission"]:
            rows, options, selected = self._choice_step(
                rows,
                field="transmission",
                choices=ProductFitment.TRANSMISSION_CHOICES,
                param_name="transmission",
            )
            context["transmission_options"] = options if len(options) > 1 or selected else []

        category_ids = {row["product__category_id"] for row in rows if row["product__category_id"]}
        categories = {
            item.pk: item
            for item in self._queryset(Category).filter(pk__in=category_ids, is_active=True)
        }
        category_options = self._options(
            rows,
            "product__category_id",
            categories,
            lambda item: item.name,
            "category",
            broad="__no_broad_category__",
        )
        category = self._selected_option(category_options, "category")
        if category is not None:
            rows = [row for row in rows if row["product__category_id"] == category]
        context["category_options"] = category_options if len(category_options) > 1 or category else []

        if self.criteria["position"]:
            rows, options, selected = self._choice_step(
                rows,
                field="position",
                choices=ProductFitment.POSITION_CHOICES,
                param_name="position",
            )
            context["position_options"] = options if len(options) > 1 or selected else []

        product_ids = {row["product_id"] for row in rows}
        product_queryset = self.products.filter(pk__in=product_ids).select_related(
            "category", "image_asset",
        ).order_by("name")
        count = product_queryset.count()
        context.update({
            "products": list(product_queryset[:100]),
            "product_count": count,
            "result_limited": count > 100,
            "show_results": True,
            "breadcrumbs": self.breadcrumbs,
            "selected_year": year,
        })
        return context
