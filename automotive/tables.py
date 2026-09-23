import django_tables2 as tables
from dlux.tables import DluxTable

from common.i18n import t
from common.tables import ModalRowActionsMixin

from .models import VehicleEngine, VehicleGeneration, VehicleMake, VehicleModel, VehicleTrim


class AutomotiveReferenceTable(ModalRowActionsMixin, DluxTable):
    row_delete_action = False


class VehicleMakeTable(AutomotiveReferenceTable):
    class Meta(DluxTable.Meta):
        model = VehicleMake
        fields = ("name", "is_active", "created_at")
        dlux_actions = True


class VehicleModelTable(AutomotiveReferenceTable):
    class Meta(DluxTable.Meta):
        model = VehicleModel
        fields = ("make", "name", "is_active", "created_at")
        dlux_actions = True


class VehicleGenerationTable(AutomotiveReferenceTable):
    class Meta(DluxTable.Meta):
        model = VehicleGeneration
        fields = ("vehicle_model", "name", "chassis_code", "year_from", "year_to", "is_active")
        dlux_actions = True


class VehicleEngineTable(AutomotiveReferenceTable):
    displacement = tables.Column(verbose_name="Displacement (L)")

    class Meta(DluxTable.Meta):
        model = VehicleEngine
        fields = (
            "vehicle_model", "generation", "display_name", "engine_code",
            "displacement", "fuel_type", "is_active",
        )
        dlux_actions = True

    def render_fuel_type(self, record):
        return t(f"fuel_{record.fuel_type}", record.get_fuel_type_display()) if record.fuel_type else "—"


class VehicleTrimTable(AutomotiveReferenceTable):
    class Meta(DluxTable.Meta):
        model = VehicleTrim
        fields = ("vehicle_model", "generation", "name", "is_active")
        dlux_actions = True
