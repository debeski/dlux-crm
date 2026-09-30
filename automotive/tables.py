import django_tables2 as tables
from dlux.tables import DluxTable

from common.i18n import t
from common.tables import ModalRowActionsMixin

from .models import EquipmentType, VehicleEngine, VehicleGeneration, VehicleMake, VehicleModel, VehicleTrim


class AutomotiveReferenceTable(ModalRowActionsMixin, DluxTable):
    row_delete_action = False


class EquipmentTypeTable(AutomotiveReferenceTable):
    class Meta(DluxTable.Meta):
        model = EquipmentType
        fields = ("name", "is_active", "created_at")
        dlux_actions = True


class VehicleMakeTable(AutomotiveReferenceTable):
    class Meta(DluxTable.Meta):
        model = VehicleMake
        fields = ("name", "is_active", "created_at")
        dlux_actions = True


class VehicleModelTable(AutomotiveReferenceTable):
    class Meta(DluxTable.Meta):
        model = VehicleModel
        fields = ("make", "equipment_type", "name", "is_active", "created_at")
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
            "vehicle_model", "generation", "manufacturer", "display_name", "engine_code",
            "displacement", "fuel_type", "is_active",
        )
        dlux_actions = True

    def render_vehicle_model(self, record, value):
        if record.vehicle_model_id:
            return str(value)
        count = record.fitted_models.count()
        return t("engine_shared_models", "Shared · {count} models").format(count=count)

    def render_fuel_type(self, record):
        return t(f"fuel_{record.fuel_type}", record.get_fuel_type_display()) if record.fuel_type else "—"


class VehicleTrimTable(AutomotiveReferenceTable):
    class Meta(DluxTable.Meta):
        model = VehicleTrim
        fields = ("vehicle_model", "generation", "name", "is_active")
        dlux_actions = True
