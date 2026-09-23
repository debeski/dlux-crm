from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from catalog.filters import ProductFilter
from catalog.models import Product

from automotive.forms import ProductFitmentFormSet, VehicleEngineForm
from automotive.models import (
    ProductFitment,
    VehicleEngine,
    VehicleGeneration,
    VehicleMake,
    VehicleModel,
    VehicleTrim,
)
from automotive.translations import DLUX_STRINGS


User = get_user_model()
ALL_CRITERIA = {
    "generation_chassis": True,
    "engine": True,
    "fuel_type": True,
    "trim": True,
    "transmission": True,
    "position": True,
}
ENABLED = {"automotive": {"enabled": True, "criteria": ALL_CRITERIA}}
DISABLED = {"automotive": {"enabled": False, "criteria": ALL_CRITERIA}}


class AutomotiveManagementTests(TestCase):
    def setUp(self):
        from dlux.models import SystemSettings

        settings = SystemSettings.load()
        settings.is_configured = True
        settings.save(update_fields=["is_configured"])
        self.user = User.objects.create_superuser("automotive-admin", "auto@example.com", "x")
        self.client.force_login(self.user)
        self.make = VehicleMake.objects.create(name="Toyota")
        self.model = VehicleModel.objects.create(make=self.make, name="Corolla")
        self.other_model = VehicleModel.objects.create(make=self.make, name="Camry")
        self.generation = VehicleGeneration.objects.create(
            vehicle_model=self.model,
            name="E170",
            chassis_code="ZRE172",
            year_from=2014,
            year_to=2019,
        )
        self.other_generation = VehicleGeneration.objects.create(
            vehicle_model=self.other_model,
            name="XV50",
            year_from=2012,
            year_to=2017,
        )
        self.engine = VehicleEngine.objects.create(
            vehicle_model=self.model,
            generation=self.generation,
            engine_code="2ZR-FE",
            display_name="1.8L",
            fuel_type=VehicleEngine.FUEL_GASOLINE,
        )
        self.trim = VehicleTrim.objects.create(
            vehicle_model=self.model,
            generation=self.generation,
            name="GLI",
        )
        self.product = Product.objects.create(name="Front Brake Pad", sku="BRK-1")

    def test_automotive_translations_keep_english_arabic_key_parity(self):
        self.assertEqual(set(DLUX_STRINGS["en"]), set(DLUX_STRINGS["ar"]))

    def enabled(self, criteria=None):
        value = {"automotive": {"enabled": True, "criteria": criteria or ALL_CRITERIA}}
        return patch("automotive.settings.get_optional_enhancements_config", return_value=value)

    def test_all_automotive_surfaces_are_hidden_when_switch_is_off(self):
        with patch("automotive.settings.get_optional_enhancements_config", return_value=DISABLED):
            self.assertEqual(self.client.get(reverse("automotive:hub")).status_code, 404)
            modal = reverse("scoped_modal_manager", args=["automotive", "VehicleMake", "new"])
            self.assertEqual(self.client.get(modal).status_code, 404)

    def test_hub_shows_only_enabled_reference_dimensions(self):
        criteria = {**ALL_CRITERIA, "generation_chassis": False, "trim": False}
        with self.enabled(criteria):
            response = self.client.get(reverse("automotive:hub"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("automotive:make_list"))
        self.assertContains(response, reverse("automotive:engine_list"))
        self.assertNotContains(response, reverse("automotive:generation_list"))
        self.assertNotContains(response, reverse("automotive:trim_list"))
        with self.enabled(criteria):
            self.assertEqual(self.client.get(reverse("automotive:generation_list")).status_code, 404)
            modal = reverse("scoped_modal_manager", args=["automotive", "VehicleTrim", "new"])
            self.assertEqual(self.client.get(modal).status_code, 404)

    def test_hub_cards_share_one_interaction_style(self):
        with self.enabled():
            response = self.client.get(reverse("automotive:hub"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.decode().count("automotive-hub-card"), 7)
        self.assertContains(response, "automotive/css/hub.css")

    def test_hub_sidebar_discovery_tracks_persisted_enhancement_state(self):
        from dlux.discovery import bump_sidebar_cache_version, discover_sidebar_catalog

        with patch("automotive.settings.get_optional_enhancements_config", return_value=DISABLED):
            bump_sidebar_cache_version()
            disabled_ids = {
                entry["id"] for entry in discover_sidebar_catalog(lang_code="en")
            }
        self.assertNotIn("automotive:hub", disabled_ids)

        with self.enabled():
            bump_sidebar_cache_version()
            en_catalog = discover_sidebar_catalog(lang_code="en")
            ar_catalog = discover_sidebar_catalog(lang_code="ar")
        en_entry = next(entry for entry in en_catalog if entry["id"] == "automotive:hub")
        ar_entry = next(entry for entry in ar_catalog if entry["id"] == "automotive:hub")
        self.assertEqual(en_entry["label"], "Automotive Compatibility")
        self.assertEqual(ar_entry["label"], "توافق قطع السيارات")
        self.assertEqual(en_entry["permissions"], ["automotive.view_vehiclemake"])
        bump_sidebar_cache_version()

    def test_reference_form_constrains_generation_to_selected_model(self):
        form = VehicleEngineForm(
            data={
                "vehicle_model": self.model.pk,
                "generation": self.generation.pk,
                "display_name": "1.8L",
                "engine_code": "2ZR",
                "displacement": "1.8",
                "fuel_type": "gasoline",
                "is_active": "on",
            },
            user=self.user,
        )
        self.assertIn(self.generation, form.fields["generation"].queryset)
        self.assertNotIn(self.other_generation, form.fields["generation"].queryset)
        self.assertTrue(form.is_valid(), form.errors)

    def test_disabled_criteria_are_absent_from_reference_forms_and_tables(self):
        criteria = {**ALL_CRITERIA, "generation_chassis": False, "fuel_type": False}
        with self.enabled(criteria):
            form = VehicleEngineForm(user=self.user)
            response = self.client.get(reverse("automotive:engine_list"))
        self.assertNotIn("generation", form.fields)
        self.assertNotIn("fuel_type", form.fields)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'data-dlux-table-col="fuel_type"')
        self.assertNotContains(response, 'name="fuel_type"')

    def test_dependencies_are_constrained_and_criterion_aware(self):
        criteria = {**ALL_CRITERIA, "trim": False}
        with self.enabled(criteria):
            response = self.client.get(reverse("automotive:dependencies"))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(any(row["id"] == self.generation.pk for row in payload["generations"]))
        self.assertTrue(any(row["id"] == self.engine.pk for row in payload["engines"]))
        self.assertEqual(payload["trims"], [])

    def test_editor_hides_disabled_fields(self):
        criteria = {**ALL_CRITERIA, "generation_chassis": False, "trim": False, "position": False}
        with self.enabled(criteria):
            response = self.client.get(reverse("automotive:product_fitments", args=[self.product.pk]))
        self.assertEqual(response.status_code, 200)
        form = response.context["formset"].forms[0]
        self.assertNotIn("generation", form.fields)
        self.assertNotIn("trim", form.fields)
        self.assertNotIn("position", form.fields)
        self.assertIn("engine", form.fields)

    def test_editor_saves_multiple_rows_without_changing_product_or_stock(self):
        initial_stock = self.product.stock_qty
        data = {
            "fitments-TOTAL_FORMS": "2",
            "fitments-INITIAL_FORMS": "0",
            "fitments-MIN_NUM_FORMS": "0",
            "fitments-MAX_NUM_FORMS": "1000",
            "fitments-0-vehicle_model": str(self.model.pk),
            "fitments-0-year_from": "2014",
            "fitments-0-year_to": "2016",
            "fitments-0-generation": str(self.generation.pk),
            "fitments-0-engine": str(self.engine.pk),
            "fitments-0-trim": str(self.trim.pk),
            "fitments-0-transmission": "automatic",
            "fitments-0-position": "front",
            "fitments-0-notes": "",
            "fitments-1-vehicle_model": str(self.model.pk),
            "fitments-1-year_from": "2017",
            "fitments-1-year_to": "2019",
            "fitments-1-generation": str(self.generation.pk),
            "fitments-1-engine": str(self.engine.pk),
            "fitments-1-trim": str(self.trim.pk),
            "fitments-1-transmission": "automatic",
            "fitments-1-position": "front",
            "fitments-1-notes": "",
        }
        with self.enabled():
            response = self.client.post(
                reverse("automotive:product_fitments", args=[self.product.pk]),
                data,
            )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.product.automotive_fitments.count(), 2)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_qty, initial_stock)

    def test_overlap_requires_explicit_confirmation(self):
        data = {
            "fitments-TOTAL_FORMS": "2",
            "fitments-INITIAL_FORMS": "0",
            "fitments-MIN_NUM_FORMS": "0",
            "fitments-MAX_NUM_FORMS": "1000",
            "fitments-0-vehicle_model": str(self.model.pk),
            "fitments-0-year_from": "2014",
            "fitments-0-year_to": "2017",
            "fitments-0-generation": str(self.generation.pk),
            "fitments-0-engine": str(self.engine.pk),
            "fitments-0-trim": str(self.trim.pk),
            "fitments-0-transmission": "automatic",
            "fitments-0-position": "front",
            "fitments-1-vehicle_model": str(self.model.pk),
            "fitments-1-year_from": "2016",
            "fitments-1-year_to": "2019",
            "fitments-1-generation": str(self.generation.pk),
            "fitments-1-engine": str(self.engine.pk),
            "fitments-1-trim": str(self.trim.pk),
            "fitments-1-transmission": "automatic",
            "fitments-1-position": "front",
        }
        formset = ProductFitmentFormSet(
            data=data,
            instance=self.product,
            prefix="fitments",
            criteria=ALL_CRITERIA,
            user=self.user,
        )
        self.assertFalse(formset.is_valid())
        self.assertIn("overlap", str(formset.non_form_errors()).lower())
        confirmed = ProductFitmentFormSet(
            data=data,
            instance=self.product,
            prefix="fitments",
            criteria=ALL_CRITERIA,
            confirm_overlaps=True,
            user=self.user,
        )
        self.assertTrue(confirmed.is_valid(), confirmed.errors)

    def test_product_card_and_keyword_search_use_fitment_only_when_enabled(self):
        ProductFitment.objects.create(
            product=self.product,
            vehicle_model=self.model,
            year_from=2014,
            year_to=2019,
            generation=self.generation,
            engine=self.engine,
            trim=self.trim,
            position=ProductFitment.POSITION_FRONT,
        )
        with self.enabled():
            response = self.client.get(reverse("catalog:product_card", args=[self.product.pk]))
            enabled_results = ProductFilter({"keyword": "ZRE172"}, queryset=Product.objects.all()).qs
        html = response.json()["html"]
        self.assertIn("Toyota Corolla", html)
        self.assertIn("2014–2019", html)
        self.assertIn(self.product, enabled_results)

        with patch("automotive.settings.get_optional_enhancements_config", return_value=DISABLED):
            response = self.client.get(reverse("catalog:product_card", args=[self.product.pk]))
            disabled_results = ProductFilter({"keyword": "ZRE172"}, queryset=Product.objects.all()).qs
        self.assertNotIn("Toyota Corolla", response.json()["html"])
        self.assertNotIn(self.product, disabled_results)
