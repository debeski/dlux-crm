import json
from datetime import date
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.test import RequestFactory, TestCase
from django.urls import reverse

from catalog.models import Product

from automotive.options_forms import OptionalEnhancementsSettingsForm
from automotive.models import (
    ProductFitment,
    VehicleEngine,
    VehicleGeneration,
    VehicleMake,
    VehicleModel,
    VehicleTrim,
)
from automotive.settings import (
    OPTIONAL_ENHANCEMENTS_NS,
    automotive_criterion_enabled,
    automotive_enabled,
    get_automotive_config,
    normalize_optional_enhancements,
)


User = get_user_model()


class OptionalEnhancementsConfigTests(TestCase):
    def test_missing_config_is_off_with_recommended_criteria_ready(self):
        with patch("dlux.utils.get_app_system_config", return_value=None):
            config = get_automotive_config()
        self.assertFalse(config["enabled"])
        self.assertTrue(all(config["criteria"].values()))

    def test_helpers_require_master_switch_and_known_criterion(self):
        stored = {
            "automotive": {
                "enabled": True,
                "criteria": {
                    "generation_chassis": False,
                    "engine": True,
                    "fuel_type": False,
                    "trim": True,
                    "transmission": True,
                    "position": True,
                },
            },
        }
        with patch("dlux.utils.get_app_system_config", return_value=stored):
            self.assertTrue(automotive_enabled())
            self.assertFalse(automotive_criterion_enabled("generation_chassis"))
            self.assertTrue(automotive_criterion_enabled("engine"))
            self.assertFalse(automotive_criterion_enabled("unknown"))

    def test_fuel_dependency_normalizes_engine_on(self):
        config = normalize_optional_enhancements({
            "automotive": {
                "enabled": True,
                "criteria": {"engine": False, "fuel_type": True},
            },
        })
        self.assertTrue(config["automotive"]["criteria"]["engine"])

    def test_settings_tile_is_registered(self):
        import automotive.dlux_options  # noqa: F401
        import dlux.options as options

        self.assertIn(OPTIONAL_ENHANCEMENTS_NS, options._SETTINGS_REGISTRY)
        definition = options._SETTINGS_REGISTRY[OPTIONAL_ENHANCEMENTS_NS]
        self.assertIs(definition["form_class"], OptionalEnhancementsSettingsForm)

    def test_superuser_can_save_nested_config(self):
        import automotive.dlux_options  # noqa: F401
        from dlux.views.options import app_settings_modal_view

        user = User.objects.create_superuser("enhancements-admin", "admin@example.com", "x")
        request = RequestFactory().post(
            "/options/app-settings/",
            data={
                "automotive_enabled": "on",
                "criterion_generation_chassis": "on",
                "criterion_engine": "on",
                "criterion_trim": "on",
                "criterion_position": "on",
            },
        )
        request.user = user
        response = app_settings_modal_view(request, OPTIONAL_ENHANCEMENTS_NS)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(json.loads(response.content)["success"])

        from dlux.models import SystemSettings

        stored = SystemSettings.load().extra_config["app"][OPTIONAL_ENHANCEMENTS_NS]
        self.assertTrue(stored["automotive"]["enabled"])
        self.assertTrue(stored["automotive"]["criteria"]["engine"])
        self.assertFalse(stored["automotive"]["criteria"]["fuel_type"])

    def test_non_superuser_cannot_save_settings(self):
        import automotive.dlux_options  # noqa: F401
        from dlux.views.options import app_settings_modal_view

        user = User.objects.create_user("enhancements-plain", password="x")
        request = RequestFactory().post(
            "/options/app-settings/",
            data={"automotive_enabled": "on"},
        )
        request.user = user
        with self.assertRaises(PermissionDenied):
            app_settings_modal_view(request, OPTIONAL_ENHANCEMENTS_NS)

    def test_manage_vehicle_data_requires_persisted_enabled_setting(self):
        import automotive.dlux_options  # noqa: F401
        from dlux.models import SystemSettings
        from dlux.options import write_app_system_config

        settings = SystemSettings.load()
        settings.is_configured = True
        settings.save(update_fields=["is_configured"])
        user = User.objects.create_superuser("options-render", "render@example.com", "x")
        self.client.force_login(user)
        url = reverse("dlux_app_settings_modal", args=[OPTIONAL_ENHANCEMENTS_NS])

        disabled = self.client.get(url)
        self.assertEqual(disabled.status_code, 200)
        disabled_html = disabled.content.decode()
        self.assertNotIn("This enhancement adds no automotive fields", disabled_html)
        self.assertIn("data-persisted-enabled='false'", disabled_html)
        self.assertIn("aria-disabled='true'", disabled_html)

        write_app_system_config(
            OPTIONAL_ENHANCEMENTS_NS,
            normalize_optional_enhancements({"automotive": {"enabled": True}}),
        )
        enabled = self.client.get(url)
        enabled_html = enabled.content.decode()
        self.assertIn("data-persisted-enabled='true'", enabled_html)
        self.assertIn("href='/staff/automotive/'", enabled_html)


class AutomotiveModelTests(TestCase):
    def setUp(self):
        self.make = VehicleMake.objects.create(name="Toyota")
        self.model = VehicleModel.objects.create(make=self.make, name="Corolla")
        self.generation = VehicleGeneration.objects.create(
            vehicle_model=self.model,
            name="E170",
            chassis_code="ZRE172",
            year_from=2014,
            year_to=2019,
        )
        self.engine = VehicleEngine.objects.create(
            vehicle_model=self.model,
            generation=self.generation,
            engine_code="2ZR-FE",
            display_name="1.8L",
            displacement="1.80",
            fuel_type=VehicleEngine.FUEL_GASOLINE,
        )
        self.trim = VehicleTrim.objects.create(
            vehicle_model=self.model,
            generation=self.generation,
            name="GLI",
        )
        self.product = Product.objects.create(name="Front Brake Pad")

    def _fitment(self, **overrides):
        values = {
            "product": self.product,
            "vehicle_model": self.model,
            "year_from": 2015,
            "year_to": 2018,
            "generation": self.generation,
            "engine": self.engine,
            "trim": self.trim,
            "transmission": ProductFitment.TRANSMISSION_AUTOMATIC,
            "position": ProductFitment.POSITION_FRONT,
        }
        values.update(overrides)
        return ProductFitment(**values)

    def test_product_schema_stays_generic(self):
        product_fields = {field.name for field in Product._meta.get_fields()}
        self.assertFalse({"make", "vehicle_model", "engine", "trim", "chassis"} & product_fields)
        self.assertIn("automotive_fitments", product_fields)

    def test_valid_qualified_fitment(self):
        fitment = self._fitment()
        fitment.full_clean()
        fitment.save()
        self.assertEqual(self.product.automotive_fitments.get(), fitment)

    def test_fitment_rejects_years_outside_generation(self):
        with self.assertRaises(ValidationError) as caught:
            self._fitment(year_from=2012).full_clean()
        self.assertIn("generation", caught.exception.message_dict)

    def test_fitment_rejects_engine_from_another_model(self):
        other_model = VehicleModel.objects.create(make=self.make, name="Camry")
        other_engine = VehicleEngine.objects.create(
            vehicle_model=other_model,
            engine_code="2AR-FE",
            display_name="2.5L",
        )
        with self.assertRaises(ValidationError) as caught:
            self._fitment(engine=other_engine).full_clean()
        self.assertIn("engine", caught.exception.message_dict)

    def test_generation_rejects_reversed_or_implausible_years(self):
        bad = VehicleGeneration(
            vehicle_model=self.model,
            name="Bad",
            year_from=date.today().year + 3,
            year_to=2000,
        )
        with self.assertRaises(ValidationError) as caught:
            bad.full_clean()
        self.assertIn("year_from", caught.exception.message_dict)
        self.assertIn("year_to", caught.exception.message_dict)

    def test_exact_duplicate_fitment_is_rejected_by_model_validation(self):
        first = self._fitment()
        first.full_clean()
        first.save()
        with self.assertRaises(ValidationError):
            self._fitment().full_clean()

    def test_used_criterion_cannot_be_disabled_while_module_remains_on(self):
        fitment = self._fitment()
        fitment.full_clean()
        fitment.save()
        current = {
            "automotive": {
                "enabled": True,
                "criteria": {
                    "generation_chassis": True,
                    "engine": True,
                    "fuel_type": True,
                    "trim": True,
                    "transmission": True,
                    "position": True,
                },
            },
        }
        form = OptionalEnhancementsSettingsForm(
            data={
                "automotive_enabled": "on",
                # generation intentionally omitted
                "criterion_engine": "on",
                "criterion_fuel_type": "on",
                "criterion_trim": "on",
                "criterion_transmission": "on",
                "criterion_position": "on",
            },
            current_value=current,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("criterion_generation_chassis", form.errors)

    def test_master_switch_can_turn_off_without_erasing_fitments(self):
        fitment = self._fitment()
        fitment.full_clean()
        fitment.save()
        form = OptionalEnhancementsSettingsForm(
            data={},
            current_value={"automotive": {"enabled": True, "criteria": {}}},
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertFalse(form.to_app_config()["automotive"]["enabled"])
        self.assertEqual(ProductFitment.objects.count(), 1)


class AutomotiveRoleTests(TestCase):
    def test_seed_roles_grants_view_to_reps_and_management_to_managers_only(self):
        call_command("seed_roles", verbosity=0)
        rep = Group.objects.get(name="Sales Representative")
        manager = Group.objects.get(name="Sales Manager")
        courier = Group.objects.get(name="Delivery Courier")

        rep_codes = set(rep.permissions.filter(content_type__app_label="automotive").values_list("codename", flat=True))
        manager_codes = set(manager.permissions.filter(content_type__app_label="automotive").values_list("codename", flat=True))
        courier_codes = set(courier.permissions.filter(content_type__app_label="automotive").values_list("codename", flat=True))

        self.assertIn("view_productfitment", rep_codes)
        self.assertNotIn("change_productfitment", rep_codes)
        self.assertIn("add_productfitment", manager_codes)
        self.assertIn("change_vehicleengine", manager_codes)
        self.assertEqual(courier_codes, set())


class OptionalEnhancementsStaticTests(TestCase):
    def test_global_script_initializes_injected_settings_modal(self):
        script = Path("automotive/static/automotive/js/optional_enhancements.js").read_text()
        include = Path("common/templates/dlux/includes/custom_scripts.html").read_text()
        self.assertIn("MutationObserver", script)
        self.assertIn("data-automotive-workflow-output", script)
        self.assertIn("persistedEnabled", script)
        self.assertIn("event.preventDefault()", script)
        self.assertIn("optional_enhancements.js", include)
