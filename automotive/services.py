from common.i18n import t


def fitment_label(fitment, criteria):
    parts = [
        f"{fitment.vehicle_model.make.name} {fitment.vehicle_model.name}",
        f"{fitment.year_from}–{fitment.year_to}",
    ]
    if criteria.get("generation_chassis") and fitment.generation_id:
        generation = fitment.generation.name
        if fitment.generation.chassis_code:
            generation = f"{generation} ({fitment.generation.chassis_code})"
        parts.append(generation)
    if criteria.get("engine") and fitment.engine_id:
        engine = fitment.engine.display_name
        if fitment.engine.engine_code:
            engine = f"{engine} ({fitment.engine.engine_code})"
        parts.append(engine)
    if criteria.get("fuel_type") and fitment.engine_id and fitment.engine.fuel_type:
        parts.append(t(f"fuel_{fitment.engine.fuel_type}", fitment.engine.get_fuel_type_display()))
    if criteria.get("trim") and fitment.trim_id:
        parts.append(fitment.trim.name)
    if criteria.get("transmission") and fitment.transmission:
        parts.append(t(f"transmission_{fitment.transmission}", fitment.get_transmission_display()))
    if criteria.get("position") and fitment.position:
        parts.append(t(f"position_{fitment.position}", fitment.get_position_display()))
    return " · ".join(parts)
