"""Quick "Fits" entry: vehicle search, chip validation, and part-number sync.

A chip is one compatibility row expressed as JSON. Chips carrying an ``id`` are
existing fitments kept as-is (their advanced fields are edited in the full
editor); chips without one describe new rows.
"""
import json
import re

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Max, Min, Q

from common.i18n import t
from common.views import scope_filtered_queryset

from .models import (
    PartProfile,
    ProductFitment,
    ProductPartNumber,
    VehicleEngine,
    VehicleGeneration,
    VehicleModel,
    VehicleTrim,
    normalize_part_number,
)
from .services import fitment_label


SEARCH_LIMIT = 25
IDENTITY_FIELDS = (
    "vehicle_model", "year_from", "year_to", "generation", "engine", "trim",
    "transmission", "position",
)
_RELATED_FIELDS = ("vehicle_model", "generation", "engine", "trim")
_RANGE = re.compile(r"((?:19|20)\d{2})\s*[-–]\s*((?:19|20)\d{2})")
_YEAR = re.compile(r"^(?:19|20)\d{2}$")
_live_generation = Q(generations__deleted_at__isnull=True, generations__is_active=True)


def _scoped(queryset, user):
    return scope_filtered_queryset(queryset, user) if user is not None else queryset


def parse_query(query):
    """Split a search into name tokens and an optional (year_from, year_to)."""
    text = _RANGE.sub(r"\1-\2", (query or "").strip())
    tokens, years = [], []
    for raw in text.split():
        match = _RANGE.fullmatch(raw)
        if match:
            years += [int(match.group(1)), int(match.group(2))]
        elif _YEAR.match(raw):
            years.append(int(raw))
        else:
            tokens.append(raw)
    return tokens, ((min(years), max(years)) if years else None)


def _generation_text(generation):
    if generation.chassis_code and generation.chassis_code != generation.name:
        return f"{generation.name} ({generation.chassis_code})"
    return generation.name


def _engine_text(engine):
    return f"{engine.display_name} ({engine.engine_code})" if engine.engine_code else engine.display_name


def chip_label(vehicle_model, year_from, year_to, generation=None, engine=None):
    parts = [f"{vehicle_model.make.name} {vehicle_model.name}"]
    if generation is not None:
        parts[0] = f"{parts[0]} {_generation_text(generation)}"
    if engine is not None:
        parts.append(_engine_text(engine))
    parts.append(f"{year_from}–{year_to}" if year_from != year_to else str(year_from))
    return " · ".join(parts)


def _chip(vehicle_model, year_from, year_to, generation=None, engine=None):
    return {
        "make": vehicle_model.make_id,
        "vehicle_model": vehicle_model.pk,
        "generation": generation.pk if generation else None,
        "engine": engine.pk if engine else None,
        "year_from": year_from,
        "year_to": year_to,
        "label": chip_label(vehicle_model, year_from, year_to, generation, engine),
    }


def _token_filter(tokens, paths):
    query = Q()
    for token in tokens:
        any_path = Q()
        for path in paths:
            any_path |= Q(**{f"{path}__icontains": token})
        query &= any_path
    return query


def _any_token(tokens, paths):
    query = Q(pk__in=[])
    for token in tokens:
        for path in paths:
            query |= Q(**{f"{path}__icontains": token})
    return query


def search_vehicles(query, *, user, criteria, limit=SEARCH_LIMIT):
    """Suggestions for a free-text vehicle search such as ``camry 2014``."""
    tokens, years = parse_query(query)
    if not tokens:
        return []

    models = _scoped(
        VehicleModel.objects.filter(is_active=True, make__is_active=True),
        user,
    ).select_related("make")
    generations = _scoped(
        VehicleGeneration.objects.filter(
            is_active=True, vehicle_model__is_active=True, vehicle_model__make__is_active=True,
        ),
        user,
    ).select_related("vehicle_model", "vehicle_model__make")
    name_paths = ("vehicle_model__make__name", "vehicle_model__name")

    results = []
    model_rows = list(
        models.filter(_token_filter(tokens, ("make__name", "name")))
        .annotate(
            span_from=Min("generations__year_from", filter=_live_generation),
            span_to=Max("generations__year_to", filter=_live_generation),
        )
        .order_by("make__name", "name")[:limit]
    )
    for vehicle_model in model_rows:
        if years:
            results.append(_chip(vehicle_model, *years))
        elif vehicle_model.span_from:
            chip = _chip(vehicle_model, vehicle_model.span_from, vehicle_model.span_to)
            chip["label"] = f"{vehicle_model.make.name} {vehicle_model.name} · {t('fits_all_years', 'all years')} ({vehicle_model.span_from}–{vehicle_model.span_to})"
            chip["all_years"] = True
            results.append(chip)
        else:
            results.append({
                "make": vehicle_model.make_id,
                "vehicle_model": vehicle_model.pk,
                "needs_year": True,
                "label": f"{vehicle_model.make.name} {vehicle_model.name} · {t('fits_type_year', 'add a year, e.g. 2015')}",
            })

    if criteria.get("generation_chassis"):
        gen_rows = generations.filter(
            _token_filter(tokens, (*name_paths, "name", "chassis_code")),
        )
        if years:
            gen_rows = gen_rows.filter(year_from__lte=years[1], year_to__gte=years[0])
        for generation in gen_rows.order_by(*name_paths, "year_from")[:limit]:
            results.append(_chip(
                generation.vehicle_model, generation.year_from, generation.year_to, generation,
            ))

    if criteria.get("engine"):
        engine_paths = ("engine_code", "display_name")
        engines = _scoped(
            VehicleEngine.objects.filter(
                is_active=True, vehicle_model__is_active=True, vehicle_model__make__is_active=True,
            ),
            user,
        ).select_related("vehicle_model", "vehicle_model__make", "generation")
        if not criteria.get("generation_chassis"):
            engines = engines.filter(generation__isnull=True)
        else:
            engines = engines.filter(Q(generation__isnull=True) | Q(generation__is_active=True))
        engines = engines.filter(
            _token_filter(tokens, (*name_paths, "generation__name", "generation__chassis_code", *engine_paths)),
        ).filter(_any_token(tokens, engine_paths))
        if years:
            engines = engines.filter(
                Q(generation__isnull=True)
                | Q(generation__year_from__lte=years[1], generation__year_to__gte=years[0]),
            )
        for engine in engines.order_by(*name_paths, "generation__year_from", "display_name")[:limit]:
            generation = engine.generation
            if generation is not None:
                span = (generation.year_from, generation.year_to)
            elif years:
                span = years
            else:
                continue
            results.append(_chip(engine.vehicle_model, *span, generation, engine))

    return results[:limit]


def fitment_chip(fitment, criteria):
    return {"id": fitment.pk, "label": fitment_label(fitment, criteria)}


def product_chips(product, criteria, *, as_new=False):
    """Chips for a product's live fitments; ``as_new`` drops ids for copying."""
    fitments = product.automotive_fitments.select_related(
        "vehicle_model", "vehicle_model__make", "generation", "engine", "trim",
    ).order_by("vehicle_model__make__name", "vehicle_model__name", "year_from", "year_to")
    chips = []
    for fitment in fitments:
        chip = fitment_chip(fitment, criteria)
        if as_new:
            chip.pop("id")
            chip.update({
                "vehicle_model": fitment.vehicle_model_id,
                "generation": fitment.generation_id,
                "engine": fitment.engine_id,
                "trim": fitment.trim_id,
                "transmission": fitment.transmission,
                "position": fitment.position,
                "year_from": fitment.year_from,
                "year_to": fitment.year_to,
            })
        chips.append(chip)
    return chips


def dump_chips(chips):
    return json.dumps(chips, ensure_ascii=False)


def _integer(value):
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValidationError(t("fits_invalid", "A vehicle entry could not be read. Remove it and add it again."))


def _values_identity(values):
    return tuple(getattr(values.get(field), "pk", values.get(field)) or None for field in IDENTITY_FIELDS)


def _fitment_identity(fitment):
    return tuple(
        getattr(fitment, f"{field}_id" if field in _RELATED_FIELDS else field) or None
        for field in IDENTITY_FIELDS
    )


def parse_chips(raw, *, user, criteria, existing_ids=()):
    """Validate posted chip JSON into ``(kept_ids, new_rows)``.

    ``new_rows`` are dicts of ProductFitment field values, deduplicated. Criteria
    the store switched off are ignored rather than rejected.
    """
    if not raw:
        return set(), []
    try:
        items = json.loads(raw)
    except (TypeError, ValueError):
        raise ValidationError(t("fits_invalid", "A vehicle entry could not be read. Remove it and add it again."))
    if not isinstance(items, list):
        raise ValidationError(t("fits_invalid", "A vehicle entry could not be read. Remove it and add it again."))

    existing_ids = set(existing_ids)
    kept, rows, seen = set(), [], set()
    models = _scoped(VehicleModel.objects.filter(is_active=True, make__is_active=True), user)
    generations = _scoped(VehicleGeneration.objects.filter(is_active=True), user)
    engines = _scoped(VehicleEngine.objects.filter(is_active=True), user)
    trims = _scoped(VehicleTrim.objects.filter(is_active=True), user)
    transmissions = {value for value, _ in ProductFitment.TRANSMISSION_CHOICES}
    positions = {value for value, _ in ProductFitment.POSITION_CHOICES}

    for item in items:
        if not isinstance(item, dict):
            raise ValidationError(t("fits_invalid", "A vehicle entry could not be read. Remove it and add it again."))
        if item.get("id") is not None:
            fitment_id = _integer(item["id"])
            if fitment_id in existing_ids:
                kept.add(fitment_id)
            continue

        label = item.get("label") or ""
        vehicle_model = models.select_related("make").filter(pk=_integer(item.get("vehicle_model"))).first()
        year_from, year_to = _integer(item.get("year_from")), _integer(item.get("year_to"))
        if vehicle_model is None or year_from is None or year_to is None:
            raise ValidationError(t("fits_needs_vehicle_year", "Each vehicle needs a model and years: {label}").format(label=label))

        values = {"vehicle_model": vehicle_model, "year_from": year_from, "year_to": year_to}
        related = (
            ("generation", generations, criteria.get("generation_chassis")),
            ("engine", engines, criteria.get("engine")),
            ("trim", trims, criteria.get("trim")),
        )
        for field, queryset, enabled in related:
            identifier = _integer(item.get(field))
            if enabled and identifier:
                obj = queryset.filter(pk=identifier).first()
                if obj is None:
                    raise ValidationError(t("fits_invalid", "A vehicle entry could not be read. Remove it and add it again."))
                values[field] = obj
        transmission = item.get("transmission") or ""
        if criteria.get("transmission") and transmission in transmissions:
            values["transmission"] = transmission
        position = item.get("position") or ""
        if criteria.get("position") and position in positions:
            values["position"] = position

        candidate = ProductFitment(**values)
        try:
            candidate.clean()
        except ValidationError as error:
            messages = "; ".join(error.messages)
            raise ValidationError(f"{label}: {messages}" if label else messages)

        key = _values_identity(values)
        if key not in seen:
            seen.add(key)
            rows.append(values)
    return kept, rows


def apply_chips(product, kept_ids, rows, *, replace):
    """Create the new rows; with ``replace`` also retire fitments not kept."""
    live = product.automotive_fitments.all()
    removed = 0
    with transaction.atomic():
        if replace:
            for fitment in live.exclude(pk__in=kept_ids):
                fitment.delete()
                removed += 1
        existing = {_fitment_identity(fitment) for fitment in product.automotive_fitments.all()}
        created = 0
        for values in rows:
            key = _values_identity(values)
            if key in existing:
                continue
            ProductFitment.objects.create(product=product, scope=product.scope, **values)
            existing.add(key)
            created += 1
    return created, removed


def split_part_numbers(text):
    """Comma, semicolon or newline separated numbers, deduplicated by normal form."""
    numbers, seen = [], set()
    for raw in re.split(r"[,;\n]+", text or ""):
        number = raw.strip()
        normalized = normalize_part_number(number)
        if not normalized or normalized in seen:
            continue
        if len(number) > 80:
            raise ValidationError(t("part_number_too_long", "Part numbers are limited to 80 characters."))
        seen.add(normalized)
        numbers.append(number)
    return numbers


def part_identity_initial(product):
    profile = PartProfile.objects.filter(product=product).first() if product and product.pk else None
    numbers = {ProductPartNumber.KIND_OEM: [], ProductPartNumber.KIND_CROSS: []}
    if product and product.pk:
        for part_number in product.part_numbers.order_by("pk"):
            numbers[part_number.kind].append(part_number.number)
    return {
        "part_brand": profile.part_brand if profile else "",
        "oem_numbers": ", ".join(numbers[ProductPartNumber.KIND_OEM]),
        "cross_references": ", ".join(numbers[ProductPartNumber.KIND_CROSS]),
    }


def save_part_identity(product, *, brand, oem_numbers, cross_references):
    with transaction.atomic():
        profile = PartProfile.all_objects.filter(product=product).first()
        if profile is None:
            if brand:
                PartProfile.objects.create(product=product, scope=product.scope, part_brand=brand)
        else:
            profile.part_brand = brand
            profile.deleted_at = None
            profile.save()

        for kind, numbers in (
            (ProductPartNumber.KIND_OEM, oem_numbers),
            (ProductPartNumber.KIND_CROSS, cross_references),
        ):
            wanted = {normalize_part_number(number): number for number in numbers}
            for part_number in product.part_numbers.filter(kind=kind):
                if part_number.normalized not in wanted:
                    part_number.delete()
                    continue
                if part_number.number != wanted[part_number.normalized]:
                    part_number.number = wanted[part_number.normalized]
                    part_number.save()
                wanted.pop(part_number.normalized)
            for number in wanted.values():
                ProductPartNumber.objects.create(
                    product=product, scope=product.scope, kind=kind, number=number,
                )


def part_number_q(value, prefix=""):
    """Product filter matching any live OEM or cross-reference number."""
    normalized = normalize_part_number(value)
    if len(normalized) < 3:
        return Q(pk__in=[])
    return Q(**{
        f"{prefix}part_numbers__normalized__contains": normalized,
        f"{prefix}part_numbers__deleted_at__isnull": True,
    }) | Q(**{
        f"{prefix}part_profile__part_brand__icontains": value,
        f"{prefix}part_profile__deleted_at__isnull": True,
    })


def products_with_fitments(query, *, user, limit=15):
    from catalog.models import Product

    products = _scoped(Product.objects.filter(is_active=True), user)
    text = (query or "").strip()
    if text:
        products = products.filter(
            Q(name__icontains=text) | Q(sku__icontains=text) | Q(barcode__icontains=text)
            | part_number_q(text),
        )
    products = products.annotate(
        fit_count=Count(
            "automotive_fitments",
            filter=Q(automotive_fitments__deleted_at__isnull=True),
            distinct=True,
        ),
    ).filter(fit_count__gt=0).order_by("name").distinct()
    return [
        {"id": product.pk, "label": str(product), "count": product.fit_count}
        for product in products[:limit]
    ]
