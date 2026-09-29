from collections import defaultdict
from urllib.parse import urlencode

from django.core.exceptions import FieldDoesNotExist
from django.db.models import Q
from django.urls import reverse

from dlux.utils import get_user_scope, is_scope_enabled

from catalog.models import Category, Product
from common.i18n import t

from .fits import part_number_q
from .models import (
    MIN_VEHICLE_YEAR,
    EquipmentType,
    ProductFitment,
    VehicleEngine,
    VehicleGeneration,
    VehicleMake,
    VehicleModel,
    VehicleTrim,
)


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
            Q(vehicle_model__is_active=True, vehicle_model__make__is_active=True)
            | Q(vehicle_model__isnull=True, engine__isnull=False),
            product__is_active=True,
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

    def _expanded_rows(self):
        """Fitment rows keyed by machine; an engine-only row repeats for every
        active model its shared engine is fitted to."""
        fields = (
            *self.row_fields, "vehicle_model_id", "vehicle_model__make_id",
            "vehicle_model__equipment_type_id",
        )
        rows, engine_rows = [], []
        for row in self.fitments.values(*fields):
            row["make_id"] = row.pop("vehicle_model__make_id")
            row["equipment_type_id"] = row.pop("vehicle_model__equipment_type_id")
            (rows if row["vehicle_model_id"] else engine_rows).append(row)
        if not engine_rows:
            return rows
        through = VehicleEngine.fitted_models.through
        live_models = self._queryset(VehicleModel).filter(is_active=True, make__is_active=True)
        fitted = defaultdict(list)
        for link in through.objects.filter(
            vehicleengine_id__in={row["engine_id"] for row in engine_rows},
            vehiclemodel__in=live_models,
        ).values("vehicleengine_id", "vehiclemodel_id", "vehiclemodel__make_id", "vehiclemodel__equipment_type_id"):
            fitted[link["vehicleengine_id"]].append(link)
        for row in engine_rows:
            for link in fitted[row["engine_id"]]:
                rows.append({
                    **row,
                    "vehicle_model_id": link["vehiclemodel_id"],
                    "make_id": link["vehiclemodel__make_id"],
                    "equipment_type_id": link["vehiclemodel__equipment_type_id"],
                })
        return rows

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

    def _select_or_reach(self, options, param_name, lookup):
        """Select a requested vehicle even when no product fits it yet.

        Staff reach an empty vehicle from the quick vehicle search to add its
        first part; it joins the options with a zero count instead of being
        rejected for having no fitments.
        """
        selected = self._selected_option(options, param_name)
        if selected is not None or not self.params.get(param_name):
            return selected
        found = lookup(_integer(self.params.get(param_name)))
        if found is None:
            return None
        identifier, label = found
        params = {**self.base_params, param_name: identifier}
        options.append({"id": identifier, "label": label, "count": 0, "url": _url(params)})
        return self._selected_option(options, param_name)

    def _lookup_make(self, identifier):
        make = self._queryset(VehicleMake).filter(pk=identifier, is_active=True).first()
        return (make.pk, make.name) if make else None

    def _lookup_model(self, make_id):
        def lookup(identifier):
            vehicle_model = self._queryset(VehicleModel).filter(
                pk=identifier, make_id=make_id, is_active=True,
            ).first()
            return (vehicle_model.pk, vehicle_model.name) if vehicle_model else None
        return lookup

    @staticmethod
    def _lookup_year(year):
        from datetime import date

        if year is None or not MIN_VEHICLE_YEAR <= year <= date.today().year + 2:
            return None
        return year, str(year)

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
            | Q(extra_barcodes__code=query, extra_barcodes__deleted_at__isnull=True)
            | part_number_q(query)
        ).distinct().select_related("category", "image_asset").order_by("name")
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

        rows = self._expanded_rows()

        if self.criteria.get("equipment_type"):
            rows, type_options, _selected = self._relational_step(
                rows,
                field="equipment_type_id",
                model=EquipmentType,
                param_name="type",
                label=lambda item: item.name,
                broad="__untyped_stays_out__",
            )
            context["type_options"] = type_options

        makes = {
            item.pk: item
            for item in self._queryset(VehicleMake).filter(
                pk__in={row["make_id"] for row in rows}, is_active=True,
            )
        }
        make_options = sorted(
            self._options(rows, "make_id", makes, lambda item: item.name, "make"),
            key=lambda option: option["label"].lower(),
        )
        make_id = self._select_or_reach(make_options, "make", self._lookup_make)
        context["make_options"] = make_options
        if make_id is None:
            context["next_step"] = "make"
            context["breadcrumbs"] = self.breadcrumbs
            return context
        rows = [row for row in rows if row["make_id"] == make_id]

        vehicle_models = {
            item.pk: item
            for item in self._queryset(VehicleModel).filter(
                pk__in={row["vehicle_model_id"] for row in rows}, is_active=True,
            )
        }
        model_options = sorted(
            self._options(rows, "vehicle_model_id", vehicle_models, lambda item: item.name, "model"),
            key=lambda option: option["label"].lower(),
        )
        model_id = self._select_or_reach(model_options, "model", self._lookup_model(make_id))
        context["model_options"] = model_options
        if model_id is None:
            context["next_step"] = "model"
            context["breadcrumbs"] = self.breadcrumbs
            return context
        rows = [row for row in rows if row["vehicle_model_id"] == model_id]

        year = None
        dated = [row for row in rows if row["year_from"] is not None]
        # `any_year` lets a caller (the till's vehicle panel) list every year at once.
        wants_years = not self.params.get("any_year")
        if self.criteria.get("model_year") and wants_years and (dated or self.params.get("year")):
            year_products = defaultdict(set)
            undated = {row["product_id"] for row in rows if row["year_from"] is None}
            for row in dated:
                for value in range(row["year_from"], row["year_to"] + 1):
                    year_products[value].add(row["product_id"])
            year_options = [
                {
                    "id": value,
                    "label": str(value),
                    "count": len(product_ids | undated),
                    "url": _url({**self.base_params, "year": value}),
                }
                for value, product_ids in sorted(year_products.items(), reverse=True)
            ]
            year = self._select_or_reach(year_options, "year", self._lookup_year)
            context["year_options"] = year_options
            if year is None:
                context["next_step"] = "year"
                context["breadcrumbs"] = self.breadcrumbs
                return context
            rows = [
                row for row in rows
                if row["year_from"] is None or row["year_from"] <= year <= row["year_to"]
            ]

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
                bits = [item.label if item.is_shared else item.display_name]
                if item.engine_code and not item.is_shared:
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
            "selected_model": model_id,
            "selected_generation": self.base_params.get("generation") or _integer(self.params.get("generation")),
        })
        return context
