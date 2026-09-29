import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from catalog.models import Category, Product

from automotive.fits import parse_chips, search_vehicles
from automotive.models import (
    EquipmentType,
    ProductFitment,
    VehicleEngine,
    VehicleGeneration,
    VehicleMake,
    VehicleModel,
)
from automotive.settings import TERMINOLOGY_EQUIPMENT, TERMINOLOGY_VEHICLE


User = get_user_model()
CRITERIA = {
    "equipment_type": True,
    "model_year": False,
    "generation_chassis": True,
    "engine": True,
    "fuel_type": True,
    "trim": False,
    "transmission": False,
    "position": True,
}


def config(**criteria):
    return patch(
        "automotive.settings.get_optional_enhancements_config",
        return_value={"automotive": {"enabled": True, "criteria": {**CRITERIA, **criteria}}},
    )


class HeavyEquipmentTests(TestCase):
    def setUp(self):
        from dlux.models import SystemSettings

        settings = SystemSettings.load()
        settings.is_configured = True
        settings.save(update_fields=["is_configured"])
        self.user = User.objects.create_superuser("heavy-admin", "heavy@example.com", "x")
        self.client.force_login(self.user)
        self.excavator = EquipmentType.objects.create(name="Excavator")
        self.loader = EquipmentType.objects.create(name="Wheel Loader")
        self.cat = VehicleMake.objects.create(name="Caterpillar")
        self.jcb = VehicleMake.objects.create(name="JCB")
        self.cat_320 = VehicleModel.objects.create(make=self.cat, name="320D", equipment_type=self.excavator)
        self.cat_950 = VehicleModel.objects.create(make=self.cat, name="950H", equipment_type=self.loader)
        self.jcb_3cx = VehicleModel.objects.create(make=self.jcb, name="3CX")
        self.perkins = VehicleEngine.objects.create(
            manufacturer="Perkins", display_name="4.4L I4 Turbo Diesel", engine_code="1104C-44T", fuel_type="diesel",
        )
        self.perkins.fitted_models.set([self.cat_320, self.jcb_3cx])
        self.filters = Category.objects.create(name="Filters")
        self.oil_filter = Product.objects.create(name="Perkins Oil Filter", category=self.filters)
        self.bucket_tooth = Product.objects.create(name="320D Bucket Tooth", category=self.filters)
        ProductFitment.objects.create(product=self.oil_filter, engine=self.perkins)
        ProductFitment.objects.create(product=self.bucket_tooth, vehicle_model=self.cat_320)

    def browse(self, params, **criteria):
        with config(**criteria):
            return self.client.get(reverse("automotive:browse"), params)

    def test_engine_part_appears_on_every_fitted_machine(self):
        response = self.browse({"make": self.jcb.pk, "model": self.jcb_3cx.pk})
        self.assertEqual([p.name for p in response.context["products"]], ["Perkins Oil Filter"])
        response = self.browse({"make": self.cat.pk, "model": self.cat_320.pk})
        self.assertEqual(
            sorted(p.name for p in response.context["products"]),
            ["320D Bucket Tooth", "Perkins Oil Filter"],
        )
        response = self.browse({"make": self.cat.pk, "model": self.cat_950.pk})
        self.assertEqual(response.context["product_count"], 0)

    def test_make_counts_include_engine_parts_and_year_step_is_skipped(self):
        response = self.browse({})
        counts = {option["label"]: option["count"] for option in response.context["make_options"]}
        self.assertEqual(counts, {"Caterpillar": 2, "JCB": 1})
        response = self.browse({"make": self.cat.pk, "model": self.cat_320.pk}, model_year=True)
        self.assertTrue(response.context["show_results"])

    def test_type_chips_narrow_makes_and_leave_untyped_out(self):
        response = self.browse({"type": self.excavator.pk})
        self.assertEqual([option["label"] for option in response.context["make_options"]], ["Caterpillar"])
        types = {option["label"] for option in response.context["type_options"]}
        self.assertEqual(types, {"Excavator"})

    def test_search_offers_types_and_engine_only_chips(self):
        labels = [item["label"] for item in search_vehicles("excavator", user=self.user, criteria=CRITERIA)]
        self.assertEqual(labels, ["Caterpillar 320D · all years"])
        [chip] = search_vehicles("perkins", user=self.user, criteria=CRITERIA)
        self.assertIsNone(chip["vehicle_model"])
        self.assertEqual(chip["engine"], self.perkins.pk)
        self.assertEqual(search_vehicles("perkins", user=self.user, criteria=CRITERIA, include_shared_engines=False), [])

    def test_engine_only_chip_saves_and_years_are_dropped_when_off(self):
        raw = json.dumps([
            {"engine": self.perkins.pk, "label": "Perkins"},
            {"vehicle_model": self.cat_950.pk, "year_from": 2012, "year_to": 2015},
        ])
        _kept, rows = parse_chips(raw, user=self.user, criteria=CRITERIA)
        self.assertEqual(rows[0]["engine"], self.perkins)
        self.assertIsNone(rows[0]["vehicle_model"])
        self.assertIsNone(rows[1]["year_from"])

    def test_shared_engine_must_be_fitted_to_the_chosen_model(self):
        fitment = ProductFitment(product=self.oil_filter, vehicle_model=self.cat_950, engine=self.perkins)
        with self.assertRaises(ValidationError):
            fitment.full_clean()
        ProductFitment(product=self.bucket_tooth, vehicle_model=self.jcb_3cx, engine=self.perkins).full_clean()

    def test_product_list_vehicle_filter_counts_engine_parts(self):
        with config():
            response = self.client.get(reverse("catalog:product_list"), {"vehicle_model": self.jcb_3cx.pk})
        self.assertEqual({row.record.name for row in response.context["table"].rows}, {"Perkins Oil Filter"})


class TerminologyTests(TestCase):
    def test_switch_writes_and_withdraws_only_its_own_overrides(self):
        from dlux.models import SystemSettings

        from automotive.terminology import apply_terminology

        settings = SystemSettings.load()
        settings.translations_override = {"ar": {"models_vehiclemake": "مصنعو المعدات"}}
        settings.save()

        apply_terminology(TERMINOLOGY_EQUIPMENT)
        overrides = SystemSettings.load().translations_override
        self.assertEqual(overrides["ar"]["models_vehiclemake"], "مصنعو المعدات")
        self.assertEqual(overrides["ar"]["models_vehiclemodel"], "طرازات الآليات")
        self.assertEqual(overrides["en"]["automotive_hub"], "Equipment Compatibility")

        apply_terminology(TERMINOLOGY_VEHICLE)
        overrides = SystemSettings.load().translations_override
        self.assertEqual(overrides, {"ar": {"models_vehiclemake": "مصنعو المعدات"}})

    def test_migrate_gives_new_strings_the_stores_wording(self):
        from dlux.models import SystemSettings

        from automotive.terminology import refresh_terminology

        with patch("automotive.settings.get_automotive_config", return_value={"terminology": TERMINOLOGY_VEHICLE}):
            refresh_terminology()
        self.assertFalse(SystemSettings.load().translations_override)
        with patch("automotive.settings.get_automotive_config", return_value={"terminology": TERMINOLOGY_EQUIPMENT}):
            refresh_terminology()
        self.assertEqual(SystemSettings.load().translations_override["ar"]["pos_find_by_vehicle"], "حسب الآلية")
