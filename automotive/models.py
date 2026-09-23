from datetime import date

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q, Value
from django.db.models.functions import Coalesce, Lower

from dlux.models import ScopedModel

from catalog.models import Product


MIN_VEHICLE_YEAR = 1886


def _validate_year_range(instance, *, generation=None):
    errors = {}
    maximum = date.today().year + 2
    if instance.year_from and instance.year_from > maximum:
        errors["year_from"] = f"Year cannot be later than {maximum}."
    if instance.year_to and instance.year_to > maximum:
        errors["year_to"] = f"Year cannot be later than {maximum}."
    if instance.year_from and instance.year_to and instance.year_from > instance.year_to:
        errors["year_to"] = "Year To must be the same as or later than Year From."
    if generation and instance.year_from and instance.year_to:
        if instance.year_from < generation.year_from or instance.year_to > generation.year_to:
            errors["generation"] = (
                f"Fitment years must stay within {generation.year_from}–{generation.year_to}."
            )
    if errors:
        raise ValidationError(errors)


class VehicleMake(ScopedModel):
    name = models.CharField(max_length=120, verbose_name="Name")
    is_active = models.BooleanField(default=True, verbose_name="Active")

    class Meta:
        verbose_name = "Vehicle Make"
        verbose_name_plural = "Vehicle Makes"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                Lower("name"), F("scope_id"),
                condition=Q(deleted_at__isnull=True, scope__isnull=False),
                name="auto_make_name_scope_ci",
            ),
            models.UniqueConstraint(
                Lower("name"),
                condition=Q(deleted_at__isnull=True, scope__isnull=True),
                name="auto_make_name_global_ci",
            ),
        ]

    def __str__(self):
        return self.name


class VehicleModel(ScopedModel):
    make = models.ForeignKey(
        VehicleMake,
        on_delete=models.PROTECT,
        related_name="vehicle_models",
        verbose_name="Make",
    )
    name = models.CharField(max_length=120, verbose_name="Name")
    is_active = models.BooleanField(default=True, verbose_name="Active")

    class Meta:
        verbose_name = "Vehicle Model"
        verbose_name_plural = "Vehicle Models"
        ordering = ["make__name", "name"]
        constraints = [
            models.UniqueConstraint(
                F("make_id"), Lower("name"),
                condition=Q(deleted_at__isnull=True),
                name="auto_model_make_name_ci",
            ),
        ]

    def __str__(self):
        return f"{self.make} {self.name}"


class VehicleGeneration(ScopedModel):
    vehicle_model = models.ForeignKey(
        VehicleModel,
        on_delete=models.PROTECT,
        related_name="generations",
        verbose_name="Vehicle Model",
    )
    name = models.CharField(max_length=120, verbose_name="Generation")
    chassis_code = models.CharField(max_length=80, blank=True, verbose_name="Chassis Code")
    year_from = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(MIN_VEHICLE_YEAR)],
        verbose_name="Year From",
    )
    year_to = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(MIN_VEHICLE_YEAR)],
        verbose_name="Year To",
    )
    is_active = models.BooleanField(default=True, verbose_name="Active")

    class Meta:
        verbose_name = "Vehicle Generation"
        verbose_name_plural = "Vehicle Generations"
        ordering = ["vehicle_model__make__name", "vehicle_model__name", "year_from", "name"]
        constraints = [
            models.CheckConstraint(
                condition=Q(year_from__lte=F("year_to")),
                name="auto_gen_year_order",
            ),
            models.UniqueConstraint(
                F("vehicle_model_id"), Lower("name"), F("year_from"), F("year_to"),
                condition=Q(deleted_at__isnull=True),
                name="auto_gen_model_name_years",
            ),
        ]

    def clean(self):
        super().clean()
        _validate_year_range(self)

    def __str__(self):
        suffix = f" ({self.chassis_code})" if self.chassis_code else ""
        return f"{self.vehicle_model} {self.name}{suffix} · {self.year_from}–{self.year_to}"


class VehicleEngine(ScopedModel):
    FUEL_GASOLINE = "gasoline"
    FUEL_DIESEL = "diesel"
    FUEL_HYBRID = "hybrid"
    FUEL_ELECTRIC = "electric"
    FUEL_LPG = "lpg"
    FUEL_OTHER = "other"
    FUEL_CHOICES = (
        (FUEL_GASOLINE, "Gasoline"),
        (FUEL_DIESEL, "Diesel"),
        (FUEL_HYBRID, "Hybrid"),
        (FUEL_ELECTRIC, "Electric"),
        (FUEL_LPG, "LPG"),
        (FUEL_OTHER, "Other"),
    )

    vehicle_model = models.ForeignKey(
        VehicleModel,
        on_delete=models.PROTECT,
        related_name="engines",
        verbose_name="Vehicle Model",
    )
    generation = models.ForeignKey(
        VehicleGeneration,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="engines",
        verbose_name="Generation",
    )
    engine_code = models.CharField(max_length=80, blank=True, verbose_name="Engine Code")
    display_name = models.CharField(max_length=120, verbose_name="Engine")
    displacement = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Displacement (L)",
    )
    fuel_type = models.CharField(
        max_length=16,
        choices=FUEL_CHOICES,
        blank=True,
        verbose_name="Fuel Type",
    )
    is_active = models.BooleanField(default=True, verbose_name="Active")

    class Meta:
        verbose_name = "Vehicle Engine"
        verbose_name_plural = "Vehicle Engines"
        ordering = ["vehicle_model__make__name", "vehicle_model__name", "display_name"]
        constraints = [
            models.UniqueConstraint(
                F("vehicle_model_id"),
                Coalesce("generation_id", Value(0)),
                Lower("engine_code"),
                Lower("display_name"),
                condition=Q(deleted_at__isnull=True),
                name="auto_engine_identity_uniq",
            ),
        ]

    def clean(self):
        super().clean()
        if self.generation_id and self.generation.vehicle_model_id != self.vehicle_model_id:
            raise ValidationError({"generation": "Generation must belong to the selected model."})

    def __str__(self):
        code = f" ({self.engine_code})" if self.engine_code else ""
        return f"{self.vehicle_model} · {self.display_name}{code}"


class VehicleTrim(ScopedModel):
    vehicle_model = models.ForeignKey(
        VehicleModel,
        on_delete=models.PROTECT,
        related_name="trims",
        verbose_name="Vehicle Model",
    )
    generation = models.ForeignKey(
        VehicleGeneration,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="trims",
        verbose_name="Generation",
    )
    name = models.CharField(max_length=120, verbose_name="Trim")
    is_active = models.BooleanField(default=True, verbose_name="Active")

    class Meta:
        verbose_name = "Vehicle Trim"
        verbose_name_plural = "Vehicle Trims"
        ordering = ["vehicle_model__make__name", "vehicle_model__name", "name"]
        constraints = [
            models.UniqueConstraint(
                F("vehicle_model_id"),
                Coalesce("generation_id", Value(0)),
                Lower("name"),
                condition=Q(deleted_at__isnull=True),
                name="auto_trim_identity_uniq",
            ),
        ]

    def clean(self):
        super().clean()
        if self.generation_id and self.generation.vehicle_model_id != self.vehicle_model_id:
            raise ValidationError({"generation": "Generation must belong to the selected model."})

    def __str__(self):
        return f"{self.vehicle_model} · {self.name}"


class ProductFitment(ScopedModel):
    TRANSMISSION_AUTOMATIC = "automatic"
    TRANSMISSION_MANUAL = "manual"
    TRANSMISSION_CVT = "cvt"
    TRANSMISSION_DCT = "dct"
    TRANSMISSION_OTHER = "other"
    TRANSMISSION_CHOICES = (
        (TRANSMISSION_AUTOMATIC, "Automatic"),
        (TRANSMISSION_MANUAL, "Manual"),
        (TRANSMISSION_CVT, "CVT"),
        (TRANSMISSION_DCT, "DCT"),
        (TRANSMISSION_OTHER, "Other"),
    )

    POSITION_FRONT = "front"
    POSITION_REAR = "rear"
    POSITION_FRONT_LEFT = "front_left"
    POSITION_FRONT_RIGHT = "front_right"
    POSITION_REAR_LEFT = "rear_left"
    POSITION_REAR_RIGHT = "rear_right"
    POSITION_CHOICES = (
        (POSITION_FRONT, "Front"),
        (POSITION_REAR, "Rear"),
        (POSITION_FRONT_LEFT, "Front Left"),
        (POSITION_FRONT_RIGHT, "Front Right"),
        (POSITION_REAR_LEFT, "Rear Left"),
        (POSITION_REAR_RIGHT, "Rear Right"),
    )

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="automotive_fitments",
        verbose_name="Product",
    )
    vehicle_model = models.ForeignKey(
        VehicleModel,
        on_delete=models.PROTECT,
        related_name="product_fitments",
        verbose_name="Vehicle Model",
    )
    year_from = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(MIN_VEHICLE_YEAR)],
        verbose_name="Year From",
    )
    year_to = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(MIN_VEHICLE_YEAR)],
        verbose_name="Year To",
    )
    generation = models.ForeignKey(
        VehicleGeneration,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="product_fitments",
        verbose_name="Generation",
    )
    engine = models.ForeignKey(
        VehicleEngine,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="product_fitments",
        verbose_name="Engine",
    )
    trim = models.ForeignKey(
        VehicleTrim,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="product_fitments",
        verbose_name="Trim",
    )
    transmission = models.CharField(
        max_length=16,
        choices=TRANSMISSION_CHOICES,
        blank=True,
        verbose_name="Transmission",
    )
    position = models.CharField(
        max_length=20,
        choices=POSITION_CHOICES,
        blank=True,
        verbose_name="Position",
    )
    notes = models.TextField(blank=True, verbose_name="Notes")

    class Meta:
        verbose_name = "Product Fitment"
        verbose_name_plural = "Product Fitments"
        ordering = [
            "product__name",
            "vehicle_model__make__name",
            "vehicle_model__name",
            "year_from",
        ]
        indexes = [
            models.Index(fields=["product"], name="auto_fitment_product_idx"),
            models.Index(
                fields=["vehicle_model", "year_from", "year_to"],
                name="auto_fitment_vehicle_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(year_from__lte=F("year_to")),
                name="auto_fitment_year_order",
            ),
            models.UniqueConstraint(
                F("product_id"),
                F("vehicle_model_id"),
                F("year_from"),
                F("year_to"),
                Coalesce("generation_id", Value(0)),
                Coalesce("engine_id", Value(0)),
                Coalesce("trim_id", Value(0)),
                F("transmission"),
                F("position"),
                condition=Q(deleted_at__isnull=True),
                name="auto_fitment_identity_uniq",
            ),
        ]

    def clean(self):
        super().clean()
        generation = self.generation if self.generation_id else None
        _validate_year_range(self, generation=generation)
        errors = {}
        if generation and generation.vehicle_model_id != self.vehicle_model_id:
            errors["generation"] = "Generation must belong to the selected model."
        if self.engine_id:
            if self.engine.vehicle_model_id != self.vehicle_model_id:
                errors["engine"] = "Engine must belong to the selected model."
            elif self.engine.generation_id and self.engine.generation_id != self.generation_id:
                errors["engine"] = "Engine must belong to the selected generation."
        if self.trim_id:
            if self.trim.vehicle_model_id != self.vehicle_model_id:
                errors["trim"] = "Trim must belong to the selected model."
            elif self.trim.generation_id and self.trim.generation_id != self.generation_id:
                errors["trim"] = "Trim must belong to the selected generation."
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"{self.product} → {self.vehicle_model} · {self.year_from}–{self.year_to}"
