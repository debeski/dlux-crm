from common.i18n import t


def years_text(year_from, year_to):
    if year_from is None:
        return t("fits_all_years", "all years")
    return f"{year_from}–{year_to}" if year_from != year_to else str(year_from)


def engine_text(engine):
    if engine.is_shared:
        return engine.label
    return f"{engine.display_name} ({engine.engine_code})" if engine.engine_code else engine.display_name


def fitment_label(fitment, criteria):
    engine = fitment.engine if fitment.engine_id else None
    if fitment.vehicle_model_id:
        parts = [f"{fitment.vehicle_model.make.name} {fitment.vehicle_model.name}"]
    else:
        parts = [f"{engine.label} · {t('fits_all_machines', 'every machine with this engine')}"]
    parts.append(years_text(fitment.year_from, fitment.year_to))
    if criteria.get("generation_chassis") and fitment.generation_id:
        generation = fitment.generation.name
        if fitment.generation.chassis_code:
            generation = f"{generation} ({fitment.generation.chassis_code})"
        parts.append(generation)
    if criteria.get("engine") and engine is not None and fitment.vehicle_model_id:
        parts.append(engine_text(engine))
    if criteria.get("fuel_type") and engine is not None and engine.fuel_type:
        parts.append(t(f"fuel_{engine.fuel_type}", engine.get_fuel_type_display()))
    if criteria.get("trim") and fitment.trim_id:
        parts.append(fitment.trim.name)
    if criteria.get("transmission") and fitment.transmission:
        parts.append(t(f"transmission_{fitment.transmission}", fitment.get_transmission_display()))
    if criteria.get("position") and fitment.position:
        parts.append(t(f"position_{fitment.position}", fitment.get_position_display()))
    return " · ".join(parts)


def engines_for_model(vehicle_model_id, queryset=None):
    """Engines a machine can carry: its own plus shared engines fitted to it."""
    from django.db.models import Q

    from .models import VehicleEngine

    queryset = queryset if queryset is not None else VehicleEngine.objects.all()
    return queryset.filter(
        Q(vehicle_model_id=vehicle_model_id) | Q(vehicle_model__isnull=True, fitted_models=vehicle_model_id)
    ).distinct()
