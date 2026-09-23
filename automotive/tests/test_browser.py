from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.sessions.middleware import SessionMiddleware
from django.db import connection
from django.test import RequestFactory, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from catalog.models import Category, Product
from catalog.views import ProductListView

from automotive.browser import VehicleBrowser
from automotive.models import (
    ProductFitment,
    VehicleEngine,
    VehicleGeneration,
    VehicleMake,
    VehicleModel,
)


User = get_user_model()
CRITERIA = {
    "generation_chassis": True,
    "engine": True,
    "fuel_type": True,
    "trim": True,
    "transmission": True,
    "position": True,
}
ENABLED = {"automotive": {"enabled": True, "criteria": CRITERIA}}
DISABLED = {"automotive": {"enabled": False, "criteria": CRITERIA}}


class VehicleBrowserTests(TestCase):
    def setUp(self):
        from dlux.models import SystemSettings

        settings = SystemSettings.load()
        settings.is_configured = True
        settings.save(update_fields=["is_configured"])
        self.user = User.objects.create_superuser("browser-admin", "browser@example.com", "x")
        self.client.force_login(self.user)
        self.brakes = Category.objects.create(name="Brakes")
        self.filters = Category.objects.create(name="Filters")

        self.toyota = VehicleMake.objects.create(name="Toyota")
        self.nissan = VehicleMake.objects.create(name="Nissan")
        self.corolla = VehicleModel.objects.create(make=self.toyota, name="Corolla")
        self.camry = VehicleModel.objects.create(make=self.toyota, name="Camry")
        self.sunny = VehicleModel.objects.create(make=self.nissan, name="Sunny")
        self.e170 = VehicleGeneration.objects.create(
            vehicle_model=self.corolla,
            name="E170",
            chassis_code="ZRE172",
            year_from=2014,
            year_to=2019,
        )
        self.e180 = VehicleGeneration.objects.create(
            vehicle_model=self.corolla,
            name="E180",
            chassis_code="ZRE181",
            year_from=2017,
            year_to=2020,
        )
        self.engine_18 = VehicleEngine.objects.create(
            vehicle_model=self.corolla,
            generation=self.e170,
            display_name="1.8L",
            engine_code="2ZR-FE",
            fuel_type="gasoline",
        )
        self.engine_20 = VehicleEngine.objects.create(
            vehicle_model=self.corolla,
            generation=self.e180,
            display_name="2.0L",
            engine_code="M20A",
            fuel_type="gasoline",
        )

        self.broad = Product.objects.create(
            name="Universal Corolla Brake Pad",
            sku="BRAKE-BROAD",
            category=self.brakes,
            stock_qty=5,
            price_lyd_override="90.00",
        )
        self.specific = Product.objects.create(
            name="E170 Front Brake Pad",
            sku="BRAKE-E170",
            barcode="990011",
            category=self.brakes,
            stock_qty=0,
            price_lyd_override="110.00",
        )
        self.e180_filter = Product.objects.create(
            name="E180 Oil Filter",
            sku="FILTER-E180",
            category=self.filters,
            stock_qty=2,
            reorder_level=3,
            price_lyd_override="35.00",
        )
        self.camry_part = Product.objects.create(name="Camry Brake", sku="CAMRY-1", category=self.brakes)
        self.sunny_part = Product.objects.create(name="Sunny Brake", sku="SUNNY-1", category=self.brakes)

        ProductFitment.objects.create(
            product=self.broad,
            vehicle_model=self.corolla,
            year_from=2014,
            year_to=2020,
        )
        ProductFitment.objects.create(
            product=self.specific,
            vehicle_model=self.corolla,
            year_from=2015,
            year_to=2019,
            generation=self.e170,
            engine=self.engine_18,
            position="front",
        )
        ProductFitment.objects.create(
            product=self.specific,
            vehicle_model=self.corolla,
            year_from=2017,
            year_to=2019,
            generation=self.e170,
            engine=self.engine_18,
            position="rear",
        )
        ProductFitment.objects.create(
            product=self.e180_filter,
            vehicle_model=self.corolla,
            year_from=2017,
            year_to=2020,
            generation=self.e180,
            engine=self.engine_20,
        )
        ProductFitment.objects.create(
            product=self.camry_part,
            vehicle_model=self.camry,
            year_from=2015,
            year_to=2018,
        )
        ProductFitment.objects.create(
            product=self.sunny_part,
            vehicle_model=self.sunny,
            year_from=2013,
            year_to=2019,
        )

    def enabled(self, criteria=None):
        config = {"automotive": {"enabled": True, "criteria": criteria or CRITERIA}}
        return patch("automotive.settings.get_optional_enhancements_config", return_value=config)

    def browse(self, params=None):
        with self.enabled():
            return self.client.get(reverse("automotive:browse"), params or {})

    def test_browser_is_unreachable_when_enhancement_is_disabled(self):
        with patch("automotive.settings.get_optional_enhancements_config", return_value=DISABLED):
            response = self.client.get(reverse("automotive:browse"))
        self.assertEqual(response.status_code, 404)

    def test_guided_make_model_and_dynamic_year_steps_count_distinct_products(self):
        response = self.browse()
        self.assertEqual(response.status_code, 200)
        makes = {option["label"]: option["count"] for option in response.context["make_options"]}
        self.assertEqual(makes, {"Nissan": 1, "Toyota": 4})

        response = self.browse({"make": self.toyota.pk})
        models = {option["label"]: option["count"] for option in response.context["model_options"]}
        self.assertEqual(models, {"Camry": 1, "Corolla": 3})

        response = self.browse({"make": self.toyota.pk, "model": self.corolla.pk})
        years = {option["id"]: option["count"] for option in response.context["year_options"]}
        self.assertEqual(years[2014], 1)
        self.assertEqual(years[2017], 3)
        self.assertEqual(years[2020], 2)

    def test_specific_selection_keeps_broad_fitments_and_deduplicates_products(self):
        response = self.browse({
            "make": self.toyota.pk,
            "model": self.corolla.pk,
            "year": 2017,
            "generation": self.e170.pk,
            "engine": self.engine_18.pk,
            "category": self.brakes.pk,
            "position": "front",
        })
        self.assertEqual(response.status_code, 200)
        products = response.context["products"]
        self.assertEqual([product.pk for product in products], [self.specific.pk, self.broad.pk])
        self.assertEqual(response.context["product_count"], 2)
        html = response.content.decode()
        self.assertIn(reverse("catalog:product_card", args=[self.specific.pk]), html)
        self.assertIn("Out of stock", html)

    def test_optional_selector_is_skipped_for_one_choice_and_hidden_when_disabled(self):
        response = self.browse({
            "make": self.toyota.pk,
            "model": self.corolla.pk,
            "year": 2015,
        })
        self.assertEqual(response.context.get("generation_options"), [])

        criteria = {**CRITERIA, "generation_chassis": False, "engine": False}
        with self.enabled(criteria):
            response = self.client.get(reverse("automotive:browse"), {
                "make": self.toyota.pk,
                "model": self.corolla.pk,
                "year": 2017,
            })
        self.assertNotIn("generation_options", response.context)
        self.assertNotIn("engine_options", response.context)
        self.assertContains(response, self.broad.name)
        self.assertContains(response, self.specific.name)
        self.assertContains(response, self.e180_filter.name)

    def test_inactive_qualifier_fitments_are_not_browsable(self):
        self.e170.is_active = False
        self.e170.save(update_fields=["is_active"])
        response = self.browse({
            "make": self.toyota.pk,
            "model": self.corolla.pk,
            "year": 2017,
        })
        products = response.context["products"]
        self.assertNotIn(self.specific, products)
        self.assertIn(self.broad, products)
        self.assertIn(self.e180_filter, products)

    def test_direct_product_search_does_not_require_vehicle_path(self):
        response = self.browse({"q": "990011"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["products"], [self.specific])
        self.assertTrue(response.context["show_results"])

    def test_browser_query_count_does_not_grow_with_more_fitments(self):
        params = {
            "make": self.toyota.pk,
            "model": self.corolla.pk,
            "year": 2017,
            "generation": self.e170.pk,
        }
        baseline_request = RequestFactory().get(reverse("automotive:browse"), params)
        baseline_request.user = self.user
        with CaptureQueriesContext(connection) as baseline_queries:
            VehicleBrowser(baseline_request, ENABLED["automotive"]).build()

        products = [
            Product(name=f"Scale Part {index}", sku=f"SCALE-{index:03d}", category=self.brakes)
            for index in range(50)
        ]
        Product.objects.bulk_create(products)
        ProductFitment.objects.bulk_create([
            ProductFitment(
                product=product,
                vehicle_model=self.corolla,
                year_from=2014,
                year_to=2020,
            )
            for product in products
        ])
        request = RequestFactory().get(reverse("automotive:browse"), params)
        request.user = self.user
        with CaptureQueriesContext(connection) as queries:
            context = VehicleBrowser(request, ENABLED["automotive"]).build()
        self.assertEqual(context["product_count"], 52)
        self.assertLessEqual(len(queries), len(baseline_queries) + 1)
        self.assertTrue(all(
            "image_asset" in product._state.fields_cache
            for product in context["products"]
        ))

    def test_products_ribbon_adds_browser_action_only_when_enabled(self):
        request = RequestFactory().get(reverse("catalog:product_list"))
        SessionMiddleware(lambda req: None).process_request(request)
        request.session.save()
        request.user = self.user
        view = ProductListView()
        view.setup(request)
        with self.enabled():
            enabled_specs = view.get_ribbon_action_specs()
        with patch("automotive.settings.get_optional_enhancements_config", return_value=DISABLED):
            disabled_specs = view.get_ribbon_action_specs()
        browse_url = reverse("automotive:browse")
        self.assertTrue(any(spec.get("url") == browse_url for spec in enabled_specs))
        self.assertFalse(any(spec.get("url") == browse_url for spec in disabled_specs))
