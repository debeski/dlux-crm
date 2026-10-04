from django.db import migrations


def migrate_machines(apps, schema_editor):
    Settings = apps.get_model("dlux", "SystemSettings")
    Vehicle = apps.get_model("automotive", "VehicleModel")
    Fitment = apps.get_model("automotive", "ProductFitment")
    Type = apps.get_model("machinery", "MachineType")
    Maker = apps.get_model("machinery", "Manufacturer")
    Machine = apps.get_model("machinery", "MachineModel")
    legacy_mode = False
    for settings in Settings.objects.all():
        extra = settings.extra_config or {}
        bag = extra.get("app", {})
        optional = bag.get("switch_pos.optional_enhancements", {})
        vehicle = optional.get("automotive", {})
        if vehicle.get("terminology") == "equipment":
            legacy_mode = True
            optional.setdefault("machinery", {})["enabled"] = vehicle.get("enabled") is True
            vehicle["enabled"] = False
            vehicle["terminology"] = "vehicle"
            settings.extra_config = extra
            settings.save(update_fields=["extra_config"])
    vehicles = Vehicle.objects.select_related("equipment_type", "make").filter(deleted_at__isnull=True, make__deleted_at__isnull=True)
    if not legacy_mode:
        vehicles = vehicles.filter(equipment_type__isnull=False)
    mappings = {}
    for vehicle in vehicles:
        typ, _ = Type.objects.get_or_create(scope_id=vehicle.scope_id, name=vehicle.equipment_type.name if vehicle.equipment_type_id else "Equipment", defaults={"is_active": vehicle.equipment_type.is_active if vehicle.equipment_type_id else True})
        maker, _ = Maker.objects.get_or_create(scope_id=vehicle.scope_id, name=vehicle.make.name, defaults={"is_active": vehicle.make.is_active})
        machine, _ = Machine.objects.get_or_create(legacy_vehicle_model_id=vehicle.pk, defaults={"scope_id": vehicle.scope_id, "machine_type": typ, "manufacturer": maker, "name": vehicle.name, "alias": vehicle.alias, "is_active": vehicle.is_active})
        mappings[vehicle.pk] = machine
    for fitment in Fitment.objects.select_related("engine").filter(deleted_at__isnull=True):
        ids = {fitment.vehicle_model_id}
        if fitment.engine_id and not fitment.vehicle_model_id:
            ids.add(fitment.engine.vehicle_model_id)
            ids.update(fitment.engine.fitted_models.values_list("pk", flat=True))
        for pk in ids:
            if pk in mappings and mappings[pk].scope_id == fitment.scope_id:
                mappings[pk].products.add(fitment.product_id)

    from django.core.cache import cache
    cache.delete("SystemSettings")
    from django.db import transaction
    transaction.on_commit(lambda: cache.delete("SystemSettings"), using=schema_editor.connection.alias if schema_editor else "default")


def grant_permissions(apps, schema_editor):
    ContentType = apps.get_model("contenttypes", "ContentType")
    Permission = apps.get_model("auth", "Permission")
    Group = apps.get_model("auth", "Group")
    for model in ("machinetype", "manufacturer", "machinemodel"):
        ct, _ = ContentType.objects.get_or_create(app_label="machinery", model=model)
        for action in ("view", "add", "change", "delete"):
            perm, _ = Permission.objects.get_or_create(content_type=ct, codename=f"{action}_{model}", defaults={"name": f"Can {action} {model}"})
            if action == "view":
                for group in Group.objects.filter(name__in=["Sales Manager", "Sales Representative"]):
                    group.permissions.add(perm)
            elif action != "delete":
                for group in Group.objects.filter(name="Sales Manager"):
                    group.permissions.add(perm)


class Migration(migrations.Migration):
    dependencies = [("machinery", "0001_initial"), ("auth", "0012_alter_user_first_name_max_length")]
    operations = [migrations.RunPython(migrate_machines, migrations.RunPython.noop), migrations.RunPython(grant_permissions, migrations.RunPython.noop)]
