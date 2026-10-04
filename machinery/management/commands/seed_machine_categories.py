from django.core.management.base import BaseCommand
from django.db import transaction
from dlux.models import Scope
from catalog.models import Category, Service
from machinery.models import MachineType, Manufacturer, MachineModel


class Command(BaseCommand):
    help = "Add the client's CIFA/F8 vocabulary without changing existing products, prices or compatibility."

    def add_arguments(self, parser):
        parser.add_argument("--scope", type=int, help="Scope ID; omitted means global records.")

    @transaction.atomic
    def handle(self, *args, **options):
        scope_id = options.get("scope")
        if scope_id is not None:
            Scope.objects.get(pk=scope_id)
        typ, _ = MachineType.objects.get_or_create(scope_id=scope_id, name="Concrete pump & mixer")
        maker, _ = Manufacturer.objects.get_or_create(scope_id=scope_id, name="CIFA")
        models = {}
        for name in ("F8", "F9", "HPG", "ZOOM"):
            models[name], _ = MachineModel.objects.get_or_create(scope_id=scope_id, machine_type=typ, manufacturer=maker, name=name)
        def category(name, parent=None):
            matches = Category.objects.filter(scope_id=scope_id, name__iexact=name, parent=parent)
            if matches.count() > 1:
                from django.core.management.base import CommandError
                raise CommandError(f"Ambiguous category: {name}. Resolve duplicates before seeding.")
            return matches.first() or Category.objects.create(scope_id=scope_id, name=name, parent=parent)
        roots = {name: category(name) for name in ("Hydraulic", "Control", "S-valve", "Hopper", "Seal kit")}
        models["F8"].categories.add(*roots.values())
        hydraulic = {name: category(name, roots["Hydraulic"]) for name in ("Pump", "Motor", "Valve", "Accumulator", "Instruments", "Repair")}
        for name in ("Gear", "Piston", "Vane", "Charge", "Tandem", "Spare part"):
            category(name, hydraulic["Pump"])
        repair_category = hydraulic["Repair"]
        repair_category.is_service = True
        repair_category.full_clean()
        repair_category.save(update_fields=["is_service"])
        repair, _ = Service.objects.get_or_create(scope_id=scope_id, name="Repair", category=hydraulic["Repair"], defaults={"service_type": Service.TYPE_MAINTENANCE})
        models["F8"].services.add(repair)
        self.stdout.write(self.style.SUCCESS("Client machine vocabulary ready. F8 branches and quoted-per-job Repair service added; F9/HPG/ZOOM have no assumed fitments."))
