import json
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from catalog.models import Category, Product
from finance.models import ExchangeRate

from automotive.fits import parse_chips, parse_query, search_vehicles
from automotive.models import (
    PartProfile,
    ProductFitment,
    ProductPartNumber,
    VehicleEngine,
    VehicleGeneration,
    VehicleMake,
    VehicleModel,
)


User = get_user_model()
CRITERIA = {
    "equipment_type": True,
    "model_year": True,
    "generation_chassis": True,
    "engine": True,
    "fuel_type": True,
    "trim": True,
    "transmission": True,
    "position": True,
}


def automotive_config(enabled=True, **criteria):
    return patch(
        "automotive.settings.get_optional_enhancements_config",
        return_value={"automotive": {"enabled": enabled, "criteria": {**CRITERIA, **criteria}}},
    )


class VehicleFixtureMixin:
    def setUp(self):
        from dlux.models import SystemSettings

        settings = SystemSettings.load()
        settings.is_configured = True
        settings.save(update_fields=["is_configured"])
        ExchangeRate.objects.create(rate=Decimal("6.50"))
        self.user = User.objects.create_superuser("fits-admin", "fits@example.com", "x")
        self.client.force_login(self.user)
        self.toyota = VehicleMake.objects.create(name="Toyota")
        self.camry = VehicleModel.objects.create(make=self.toyota, name="Camry")
        self.hilux = VehicleModel.objects.create(make=self.toyota, name="Hilux")
        self.xv50 = VehicleGeneration.objects.create(
            vehicle_model=self.camry, name="7th", chassis_code="XV50", year_from=2012, year_to=2017,
        )
        self.xv70 = VehicleGeneration.objects.create(
            vehicle_model=self.camry, name="8th", chassis_code="XV70", year_from=2018, year_to=2024,
        )
        self.engine = VehicleEngine.objects.create(
            vehicle_model=self.camry, generation=self.xv50, display_name="2.5L I4",
            engine_code="2AR-FE", fuel_type="gasoline",
        )
        self.filters = Category.objects.create(name="Oil Filters")

    def chip(self, **values):
        base = {"vehicle_model": self.camry.pk, "year_from": 2012, "year_to": 2017}
        base.update(values)
        return base

    def product_modal_url(self, pk="new"):
        return reverse("scoped_modal_manager", args=["catalog", "product", pk])

    def product_payload(self, **extra):
        data = {
            "name": "Oil Filter",
            "category": self.filters.pk,
            "unit": Product.UNIT_PIECE,
            "cost_usd": "2.00",
            "markup_percent": "50",
            "price_usd": "3.00",
            "reorder_level": "0",
            "track_stock": "on",
            "is_active": "on",
        }
        data.update(extra)
        return data


class QuerySearchTests(VehicleFixtureMixin, TestCase):
    def test_parse_query_reads_years_and_ranges(self):
        self.assertEqual(parse_query("camry 2014"), (["camry"], (2014, 2014)))
        self.assertEqual(parse_query("golf 2010 - 2012"), (["golf"], (2010, 2012)))
        self.assertEqual(parse_query("hilux 2.8"), (["hilux", "2.8"], None))

    def test_year_offers_exact_year_and_containing_generation(self):
        results = search_vehicles("camry 2014", user=self.user, criteria=CRITERIA)
        labels = [item["label"] for item in results]
        self.assertIn("Toyota Camry · 2014", labels)
        self.assertIn("Toyota Camry 7th (XV50) · 2012–2017", labels)
        self.assertFalse(any("XV70" in label for label in labels))

    def test_chassis_and_engine_tokens_match(self):
        chassis = search_vehicles("xv70", user=self.user, criteria=CRITERIA)
        self.assertEqual([item["generation"] for item in chassis], [self.xv70.pk])
        engines = search_vehicles("camry 2ar", user=self.user, criteria=CRITERIA)
        self.assertEqual([item["engine"] for item in engines], [self.engine.pk])

    def test_disabled_criteria_hide_generation_and_engine_suggestions(self):
        results = search_vehicles(
            "camry", user=self.user, criteria={**CRITERIA, "generation_chassis": False, "engine": False},
        )
        self.assertTrue(all(item.get("generation") is None for item in results))

    def test_model_without_a_year_means_all_years(self):
        [item] = search_vehicles("hilux", user=self.user, criteria=CRITERIA)
        self.assertEqual((item["year_from"], item["year_to"]), (None, None))
        self.assertTrue(item["all_years"])
        [dated] = search_vehicles("hilux 2016", user=self.user, criteria=CRITERIA)
        self.assertEqual((dated["year_from"], dated["year_to"]), (2016, 2016))

    def test_search_endpoint_requires_enabled_mode(self):
        with automotive_config(enabled=False):
            self.assertEqual(self.client.get(reverse("automotive:vehicle_search"), {"q": "camry"}).status_code, 404)
        with automotive_config():
            response = self.client.get(reverse("automotive:vehicle_search"), {"q": "camry"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["results"])


class ChipValidationTests(VehicleFixtureMixin, TestCase):
    def test_duplicates_collapse_and_foreign_ids_are_ignored(self):
        raw = json.dumps([self.chip(), self.chip(), {"id": 999}])
        kept, rows = parse_chips(raw, user=self.user, criteria=CRITERIA, existing_ids={1})
        self.assertEqual(kept, set())
        self.assertEqual(len(rows), 1)

    def test_generation_must_cover_the_years(self):
        raw = json.dumps([self.chip(generation=self.xv50.pk, year_from=2010, label="Camry")])
        with self.assertRaises(ValidationError):
            parse_chips(raw, user=self.user, criteria=CRITERIA)

    def test_disabled_criteria_are_dropped_not_rejected(self):
        raw = json.dumps([self.chip(generation=self.xv50.pk, position="front")])
        _kept, [row] = parse_chips(
            raw, user=self.user, criteria={**CRITERIA, "generation_chassis": False, "position": False},
        )
        self.assertNotIn("generation", row)
        self.assertNotIn("position", row)

    def test_garbage_is_a_validation_error(self):
        for raw in ("not json", json.dumps({"a": 1}), json.dumps([self.chip(year_from=None)])):
            with self.assertRaises(ValidationError):
                parse_chips(raw, user=self.user, criteria=CRITERIA)


class ProductModalTests(VehicleFixtureMixin, TestCase):
    def test_create_saves_vehicles_brand_and_part_numbers(self):
        payload = self.product_payload(
            part_brand="Denso",
            oem_numbers="90915-YZZE1, 90915YZZE1",
            cross_references="W 68/3",
            automotive_fits=json.dumps([self.chip(generation=self.xv50.pk)]),
        )
        with automotive_config():
            response = self.client.post(self.product_modal_url(), payload)
        self.assertTrue(response.json()["success"])
        product = Product.objects.get(name="Oil Filter")
        fitment = product.automotive_fitments.get()
        self.assertEqual((fitment.generation, fitment.year_from, fitment.year_to), (self.xv50, 2012, 2017))
        self.assertEqual(PartProfile.objects.get(product=product).part_brand, "Denso")
        self.assertEqual(
            sorted(product.part_numbers.values_list("kind", "normalized")),
            [("cross", "W683"), ("oem", "90915YZZE1")],
        )

    def test_edit_removes_only_dropped_chips_and_keeps_advanced_rows(self):
        product = Product.objects.create(name="Pads", category=self.filters)
        kept = ProductFitment.objects.create(
            product=product, vehicle_model=self.camry, year_from=2012, year_to=2017,
            generation=self.xv50, engine=self.engine, position="front",
        )
        dropped = ProductFitment.objects.create(
            product=product, vehicle_model=self.camry, year_from=2018, year_to=2024,
        )
        payload = self.product_payload(
            name="Pads",
            automotive_fits=json.dumps([{"id": kept.pk}, self.chip(vehicle_model=self.hilux.pk, year_from=2016, year_to=2016)]),
        )
        with automotive_config():
            response = self.client.post(self.product_modal_url(product.pk), payload)
        self.assertTrue(response.json()["success"])
        live = product.automotive_fitments.all()
        self.assertIn(kept, live)
        self.assertNotIn(dropped, live)
        self.assertTrue(live.filter(vehicle_model=self.hilux, year_from=2016).exists())
        kept.refresh_from_db()
        self.assertEqual(kept.position, "front")

    def test_invalid_chip_rerenders_the_modal_without_saving(self):
        payload = self.product_payload(automotive_fits="broken")
        with automotive_config():
            response = self.client.post(self.product_modal_url(), payload)
        self.assertFalse(response.json()["success"])
        self.assertFalse(Product.objects.filter(name="Oil Filter").exists())

    def test_disabled_mode_leaves_the_product_form_generic(self):
        with automotive_config(enabled=False):
            html = self.client.get(self.product_modal_url()).json()["html"]
        self.assertNotIn("data-fits-picker", html)
        self.assertNotIn("oem_numbers", html)

    def test_vehicle_prefill_from_query(self):
        with automotive_config():
            html = self.client.get(
                self.product_modal_url(), {"fit_model": self.camry.pk, "fit_generation": self.xv50.pk},
            ).json()["html"]
        self.assertIn("Toyota Camry 7th (XV50) · 2012–2017", html)

    def test_user_without_fitment_permissions_cannot_post_vehicles(self):
        clerk = User.objects.create_user("clerk", password="x")
        clerk.user_permissions.add(*Permission.objects.filter(
            content_type__app_label="catalog", codename__in=["view_product", "add_product", "change_product"],
        ))
        self.client.force_login(clerk)
        payload = self.product_payload(automotive_fits=json.dumps([self.chip()]))
        with automotive_config():
            html = self.client.get(self.product_modal_url()).json()["html"]
            response = self.client.post(self.product_modal_url(), payload)
        self.assertNotIn("data-fits-picker", html)
        self.assertTrue(response.json()["success"])
        self.assertFalse(ProductFitment.objects.exists())


class SearchAndFilterTests(VehicleFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.filter = Product.objects.create(name="Filter A", category=self.filters)
        self.other = Product.objects.create(name="Filter B", category=self.filters)
        ProductPartNumber.objects.create(product=self.filter, kind="oem", number="90915-YZZE1")
        ProductFitment.objects.create(product=self.filter, vehicle_model=self.camry, year_from=2012, year_to=2017)
        ProductFitment.objects.create(product=self.other, vehicle_model=self.camry, year_from=2018, year_to=2024)

    def list_names(self, params):
        with automotive_config():
            response = self.client.get(reverse("catalog:product_list"), params)
        return {row.record.name for row in response.context["table"].rows}

    def test_keyword_matches_normalized_part_numbers(self):
        self.assertEqual(self.list_names({"keyword": "90915yzze1"}), {"Filter A"})

    def test_vehicle_filter_needs_model_and_year_on_the_same_row(self):
        self.assertEqual(self.list_names({"vehicle_model": self.camry.pk, "vehicle_year": 2014}), {"Filter A"})
        self.assertEqual(self.list_names({"vehicle_year": 2020}), {"Filter B"})

    def test_browser_direct_search_matches_part_numbers(self):
        with automotive_config():
            response = self.client.get(reverse("automotive:browse"), {"q": "90915 YZZE1"})
        self.assertEqual([product.name for product in response.context["products"]], ["Filter A"])

    def test_browser_reaches_a_vehicle_with_no_parts_and_offers_add(self):
        with automotive_config():
            response = self.client.get(
                reverse("automotive:browse"),
                {"make": self.toyota.pk, "model": self.hilux.pk, "year": 2016},
            )
        self.assertEqual(response.context["product_count"], 0)
        self.assertIn(f"fit_model={self.hilux.pk}", response.context["add_part_url"])
        self.assertIn("fit_year=2016", response.context["add_part_url"])


class BulkAndCopyTests(VehicleFixtureMixin, TestCase):
    def test_bulk_adds_vehicles_without_removing_existing(self):
        first = Product.objects.create(name="Pad 1")
        second = Product.objects.create(name="Pad 2")
        existing = ProductFitment.objects.create(product=first, vehicle_model=self.hilux, year_from=2016, year_to=2016)
        data = {"products": [first.pk, second.pk], "fits": json.dumps([self.chip(generation=self.xv50.pk)])}
        with automotive_config():
            response = self.client.post(reverse("automotive:bulk_fitments"), data)
        self.assertTrue(response.json()["success"])
        self.assertIn(existing, first.automotive_fitments.all())
        self.assertEqual(ProductFitment.objects.filter(generation=self.xv50).count(), 2)

    def test_bulk_requires_a_vehicle(self):
        product = Product.objects.create(name="Pad 1")
        with automotive_config():
            response = self.client.post(reverse("automotive:bulk_fitments"), {"products": [product.pk], "fits": "[]"})
        self.assertFalse(response.json()["success"])

    def test_bulk_is_denied_without_fitment_permissions(self):
        self.client.force_login(User.objects.create_user("viewer", password="x"))
        with automotive_config():
            self.assertEqual(self.client.get(reverse("automotive:bulk_fitments")).status_code, 403)

    def test_copy_source_lists_products_and_returns_chips_without_ids(self):
        source = Product.objects.create(name="Donor Filter")
        ProductFitment.objects.create(
            product=source, vehicle_model=self.camry, year_from=2012, year_to=2017, generation=self.xv50,
        )
        with automotive_config():
            listing = self.client.get(reverse("automotive:fits_source"), {"q": "donor"}).json()
            chips = self.client.get(reverse("automotive:fits_source"), {"product": source.pk}).json()["chips"]
        self.assertEqual(listing["products"][0]["count"], 1)
        self.assertNotIn("id", chips[0])
        self.assertEqual(chips[0]["generation"], self.xv50.pk)


class IntakeAndLandingTests(VehicleFixtureMixin, TestCase):
    def test_purchase_line_fits_attach_to_the_created_product(self):
        prefix = "form-0-"
        data = {
            "supplier": "", "supplier_name": "Parts Co", "supplier_phone": "", "supplier_address": "",
            "invoice_date": "2026-09-28", "notes": "",
            "form-TOTAL_FORMS": "1", "form-INITIAL_FORMS": "0",
            "form-MIN_NUM_FORMS": "0", "form-MAX_NUM_FORMS": "1000",
            f"{prefix}product": "", f"{prefix}name": "Camry Pads", f"{prefix}unit": Product.UNIT_PIECE,
            f"{prefix}barcode": "", f"{prefix}cost_usd": "10", f"{prefix}markup_percent": "20",
            f"{prefix}price_usd": "12", f"{prefix}price_lyd_override": "", f"{prefix}color": "",
            f"{prefix}size": "", f"{prefix}quantity": "4",
            f"{prefix}fits": json.dumps([self.chip(generation=self.xv50.pk)]),
        }
        with automotive_config():
            response = self.client.post(reverse("catalog:purchase_invoice_create"), data)
        self.assertEqual(response.status_code, 302)
        product = Product.objects.get(name="Camry Pads")
        self.assertEqual(product.automotive_fitments.get().generation, self.xv50)
