from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower
from dlux.models import ScopedModel


class MachineReference(ScopedModel):
    name = models.CharField(max_length=120, verbose_name="Name")
    is_active = models.BooleanField(default=True, verbose_name="Active")

    class Meta:
        abstract = True
        ordering = ["name"]

    def __str__(self):
        return self.name


class MachineType(MachineReference):
    class Meta(MachineReference.Meta):
        verbose_name = "Machine type"
        verbose_name_plural = "Machine types"
        constraints = [
            models.UniqueConstraint(Lower("name"), "scope", name="machine_type_scoped_name"),
            models.UniqueConstraint(Lower("name"), condition=models.Q(scope__isnull=True), name="machine_type_global_name"),
        ]


class Manufacturer(MachineReference):
    class Meta(MachineReference.Meta):
        verbose_name = "Manufacturer"
        verbose_name_plural = "Manufacturers"
        constraints = [
            models.UniqueConstraint(Lower("name"), "scope", name="machine_make_scoped_name"),
            models.UniqueConstraint(Lower("name"), condition=models.Q(scope__isnull=True), name="machine_make_global_name"),
        ]


class MachineModel(MachineReference):
    machine_type = models.ForeignKey(MachineType, on_delete=models.PROTECT, verbose_name="Machine type")
    manufacturer = models.ForeignKey(Manufacturer, on_delete=models.PROTECT, verbose_name="Manufacturer")
    alias = models.CharField(max_length=200, blank=True, verbose_name="Local alias")
    categories = models.ManyToManyField("catalog.Category", blank=True, related_name="machine_branches", verbose_name="Category branches")
    products = models.ManyToManyField("catalog.Product", blank=True, related_name="machine_models")
    services = models.ManyToManyField("catalog.Service", blank=True, related_name="machine_models")
    legacy_vehicle_model = models.OneToOneField("automotive.VehicleModel", null=True, blank=True, on_delete=models.SET_NULL, related_name="migrated_machine")

    class Meta(MachineReference.Meta):
        verbose_name = "Machine model"
        verbose_name_plural = "Machine models"
        constraints = [models.UniqueConstraint("machine_type", "manufacturer", Lower("name"), name="machine_model_type_make_name")]

    def __str__(self):
        return f"{self.machine_type} / {self.manufacturer} / {self.name}"

    def clean(self):
        super().clean()
        for field in ("machine_type", "manufacturer"):
            obj = getattr(self, field, None)
            if obj is not None and obj.scope_id != self.scope_id:
                raise ValidationError({field: "Choose a record from the same scope."})
