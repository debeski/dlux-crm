from decimal import Decimal
from importlib import import_module
from unittest.mock import patch

from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import RequestFactory, TestCase
from django.urls import reverse
from dlux.models import SystemSettings
from dlux.options import write_app_system_config

from automotive.models import VehicleMake, VehicleModel, ProductFitment
from automotive.options_forms import OptionalEnhancementsSettingsForm
from automotive.settings import OPTIONAL_ENHANCEMENTS_NS, get_optional_enhancements_config
from catalog.filters import ProductFilter
from catalog.forms import ProductForm, ServiceForm, PurchaseInvoiceLineForm
from catalog.models import Category, Product, Service, PurchaseInvoice, StockMovement
from catalog.opening_stock_import import _category, OpeningStockImportError
from finance.models import ExchangeRate
from machinery.models import MachineModel, MachineType, Manufacturer
from machinery.views import MachineBrowserView


class MachineryWorkflowTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser("machine-admin", "machines@example.com", "x")
        settings = SystemSettings.load()
        settings.is_configured = True
        settings.save(update_fields=["is_configured"])
        write_app_system_config(OPTIONAL_ENHANCEMENTS_NS, {"machinery": {"enabled": True}, "automotive": {"enabled": False}})
        call_command("seed_machine_categories", verbosity=0)
        self.model = MachineModel.objects.get(name="F8")
        self.piston = Category.objects.get(name="Piston")
        ExchangeRate.objects.create(rate=Decimal("6.50"))

    def browser(self, **params):
        params.setdefault("type", self.model.machine_type_id)
        params.setdefault("manufacturer", self.model.manufacturer_id)
        params.setdefault("model", self.model.pk)
        request = RequestFactory().get(reverse("machinery:browse"), params)
        from catalog.tests.test_purchase_invoices import _attach_request_state
        _attach_request_state(request, self.user)
        response = MachineBrowserView.as_view()(request)
        response.render()
        return response

    def test_browser_reuses_vehicle_components_and_operational_product_card(self):
        product = Product.objects.create(name="Shared card pump", category=self.piston, price_usd=20)
        self.model.products.add(product)
        response = self.browser()
        self.assertContains(response, "automotive/css/browser.css")
        self.assertContains(response, 'class="vehicle-product-card"')
        self.assertContains(response, reverse("catalog:product_card", args=[product.pk]))
        self.assertContains(response, 'data-fits-mode="jump"')

    def test_machine_jump_search_alias_and_inactive_models(self):
        self.client.force_login(self.user)
        self.model.alias = "Local machine"
        self.model.save(update_fields=["alias"])
        url = reverse("machinery:model_search")
        data = self.client.get(url, {"q": "Local machine"}).json()
        self.assertEqual(data["results"][0]["browse_params"]["model"], self.model.pk)
        self.model.is_active = False
        self.model.save(update_fields=["is_active"])
        self.assertEqual(self.client.get(url, {"q": "Local machine"}).json()["results"], [])

    def test_product_ribbon_enhancement_combinations(self):
        from catalog.views import ProductListView
        request = RequestFactory().get(reverse("catalog:product_list"))
        request.user = self.user
        request.session = {}
        for vehicles, machines in ((False, False), (True, False), (False, True), (True, True)):
            write_app_system_config(OPTIONAL_ENHANCEMENTS_NS, {"machinery": {"enabled": machines}, "automotive": {"enabled": vehicles}})
            view = ProductListView()
            view.setup(request)
            actions = view.get_ribbon_action_specs()
            urls = [action.get("url") for action in actions]
            modals = [action.get("attrs", {}).get("data-dynamic-modal") for action in actions]
            self.assertEqual(reverse("automotive:browse") in urls, vehicles and not machines)
            self.assertEqual(reverse("machinery:browse") in urls, machines and not vehicles)
            self.assertEqual(reverse("automotive:bulk_fitments") in modals, vehicles)
            self.assertEqual(reverse("machinery:bulk_assign") in modals, machines)

    def test_bulk_machine_assignment_is_additive_and_guarded(self):
        self.client.force_login(self.user)
        product = Product.objects.create(name="Bulk pump", category=self.piston, price_usd=20)
        other = MachineModel.objects.get(name="F9")
        product.machine_models.add(other)
        url = reverse("machinery:bulk_assign")
        self.assertIn("html", self.client.get(url).json())
        response = self.client.post(url, {"products": [product.pk], "machines": [self.model.pk]})
        self.assertTrue(response.json()["success"])
        self.assertSetEqual(set(product.machine_models.values_list("pk", flat=True)), {other.pk, self.model.pk})
        write_app_system_config(OPTIONAL_ENHANCEMENTS_NS, {"machinery": {"enabled": False}})
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_seed_is_idempotent_and_does_not_assume_other_model_branches(self):
        counts = (MachineModel.objects.count(), Category.objects.count(), Service.objects.count())
        call_command("seed_machine_categories", verbosity=0)
        self.assertEqual(counts, (MachineModel.objects.count(), Category.objects.count(), Service.objects.count()))
        self.assertEqual(MachineModel.objects.get(name="ZOOM").manufacturer.name, "CIFA")
        self.assertFalse(MachineModel.objects.get(name="F9").categories.exists())
        repair = Service.objects.get(name="Repair")
        self.assertIsNone(repair.selling_price_lyd())
        self.assertEqual(str(repair.category), "Hydraulic / Repair")

    def test_category_cycles_rejected_and_imports_disambiguate_full_paths(self):
        hydraulic = Category.objects.get(name="Hydraulic")
        hydraulic.parent = self.piston
        with self.assertRaises(ValidationError):
            hydraulic.full_clean()
        Category.objects.create(name="Piston", parent=Category.objects.get(name="Control"))
        with self.assertRaises(OpeningStockImportError):
            _category("Piston")
        self.assertEqual(_category("Hydraulic/Pump/Piston"), self.piston)

    def test_browser_and_catalog_parent_filter_include_descendants(self):
        product = Product.objects.create(name="Piston pump", alias="Local pump", category=self.piston, price_usd=20)
        self.model.products.add(product)
        pump = Category.objects.get(name="Pump")
        response = self.browser(category=pump.pk)
        self.assertContains(response, "Piston pump")
        self.assertContains(response, "Local pump")
        self.assertEqual(response.context_data["entries"][0]["price"], Decimal("130.00"))
        self.assertIn(product, ProductFilter({"category": pump.pk}, queryset=Product.objects.all()).qs)
        self.assertNotContains(response, 'name="engine"')
        self.assertNotContains(response, 'name="transmission"')

    def test_repair_is_service_not_stock_and_hidden_without_service_permission(self):
        repair = Category.objects.get(name="Repair")
        response = self.browser(category=repair.pk)
        self.assertEqual(len(response.context_data["entries"]), 1)
        self.assertTrue(response.context_data["entries"][0]["service"])
        self.assertFalse(Product.objects.filter(name="Repair").exists())
        self.assertNotIn("product", [kind for kind, url in response.context_data["adds"]])
        self.assertNotIn(repair, ProductForm(user=self.user).fields["category"].queryset)
        with self.assertRaises(ValidationError):
            Product(name="Wrong repair stock", category=repair).full_clean()
        self.assertFalse(StockMovement.objects.exists())
        reader = get_user_model().objects.create_user("parts-only")
        reader.user_permissions.add(*Permission.objects.filter(content_type__app_label="machinery", codename__startswith="view_"))
        reader.user_permissions.add(Permission.objects.get(content_type__app_label="catalog", codename="view_product"))
        self.user = reader
        self.assertEqual(self.browser(category=repair.pk).context_data["entries"], [])

    def test_disabled_feature_hides_forms_and_rejects_direct_routes(self):
        self.assertIn("machine_models", PurchaseInvoiceLineForm(user=self.user).fields)
        write_app_system_config(OPTIONAL_ENHANCEMENTS_NS, {"machinery": {"enabled": False}})
        self.assertNotIn("machine_models", PurchaseInvoiceLineForm(user=self.user).fields)
        self.assertNotIn("machine_models", ProductForm(user=self.user).fields)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("machinery:browse")).status_code, 404)
        self.assertEqual(self.client.get(reverse("scoped_modal_manager", args=["machinery", "machinemodel", "new"])).status_code, 404)

    def test_purchase_adds_machine_compatibility_without_duplicate_stock(self):
        from catalog.tests.test_purchase_invoices import PurchaseInvoiceTests
        helpers = PurchaseInvoiceTests(methodName="test_purchase_invoice_creates_supplier_product_line_and_stock_movement")
        helpers.user = self.user
        row = helpers._row(name="Hydraulic piston pump", category=self.piston.pk, quantity="2", cost_usd="20", markup_percent="50", machine_models=[self.model.pk])
        response = helpers._post(helpers._post_data([row]))
        self.assertEqual(response.status_code, 302)
        product = Product.objects.get(name="Hydraulic piston pump")
        self.assertEqual(product.stock_qty, 2)
        self.assertEqual(product.category, self.piston)
        self.assertEqual(list(product.machine_models.all()), [self.model])
        self.assertEqual(PurchaseInvoice.objects.count(), 1)
        another = MachineModel.objects.get(name="F9")
        product.machine_models.add(another)
        self.assertEqual(Product.objects.count(), 1)
        self.assertEqual(product.stock_qty, 2)

    def test_service_form_saves_category_and_machine(self):
        form = ServiceForm({"name": "Hydraulic repair", "service_type": "maintenance", "category": Category.objects.get(name="Repair").pk, "machine_models": [self.model.pk], "is_active": "on"}, user=self.user)
        self.assertTrue(form.is_valid(), form.errors)
        service = form.save()
        self.assertEqual(list(service.machine_models.all()), [self.model])
        self.assertEqual(service.category.name, "Repair")

    def test_settings_can_enable_both_enhancements_without_vehicle_wording_changes(self):
        form = OptionalEnhancementsSettingsForm({"automotive_enabled": "on", "machinery_enabled": "on", "terminology": "equipment"})
        self.assertTrue(form.is_valid(), form.errors)
        config = form.to_app_config()
        self.assertTrue(config["automotive"]["enabled"])
        self.assertTrue(config["machinery"]["enabled"])
        self.assertEqual(config["automotive"]["terminology"], "vehicle")

    def test_legacy_machine_migration_preserves_source_and_part_stock(self):
        make = VehicleMake.objects.create(name="Legacy CIFA")
        vehicle = VehicleModel.objects.create(make=make, name="Legacy F8", alias="Old local name")
        product = Product.objects.create(name="Legacy part", stock_qty=7)
        ProductFitment.objects.create(product=product, vehicle_model=vehicle)
        write_app_system_config(OPTIONAL_ENHANCEMENTS_NS, {"automotive": {"enabled": True, "terminology": "equipment"}})
        migrate = import_module("machinery.migrations.0002_separate_legacy_machines").migrate_machines
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor
        historical_apps = MigrationExecutor(connection).loader.project_state().apps
        migrate(historical_apps, None)
        machine = MachineModel.objects.get(legacy_vehicle_model=vehicle)
        self.assertEqual(machine.alias, vehicle.alias)
        self.assertIn(product, machine.products.all())
        product.refresh_from_db()
        self.assertEqual(product.stock_qty, 7)
        self.assertTrue(VehicleModel.objects.filter(pk=vehicle.pk).exists())
        config = get_optional_enhancements_config()
        self.assertTrue(config["machinery"]["enabled"])
        self.assertFalse(config["automotive"]["enabled"])

    def test_hub_lists_and_modal_forms_use_framework_protocol(self):
        self.client.force_login(self.user)
        for name in ("hub", "type_list", "manufacturer_list", "model_list"):
            response = self.client.get(reverse(f"machinery:{name}"))
            self.assertEqual(response.status_code, 200, name)
        response = self.client.get(reverse("scoped_modal_manager", args=["machinery", "machinemodel", "new"]))
        self.assertEqual(response.status_code, 200)
        self.assertIn("html", response.json())
        self.assertNotIn("engine", response.json()["html"])
        response = self.client.get(reverse("scoped_modal_manager", args=["catalog", "product", "new"]), {"machine_model": self.model.pk, "category": self.piston.pk})
        self.assertEqual(response.status_code, 200)
        self.assertIn("machine_models", response.json()["html"])

    def test_existing_product_rejects_cross_scope_and_inactive_machine_choices(self):
        from dlux.models import Scope
        scope = Scope.objects.create(name="Other machinery store")
        typ = MachineType.objects.create(name="Foreign pump", scope=scope)
        maker = Manufacturer.objects.create(name="Foreign maker", scope=scope)
        foreign = MachineModel.objects.create(name="Foreign model", machine_type=typ, manufacturer=maker, scope=scope)
        product = Product.objects.create(name="Global part")
        for instance in (product, None):
            form = ProductForm(instance=instance, user=self.user)
            with self.assertRaises(ValidationError):
                form.fields["machine_models"].clean([foreign.pk])
        self.model.is_active = False
        self.model.save()
        with self.assertRaises(ValidationError):
            PurchaseInvoiceLineForm(user=self.user).fields["machine_models"].clean([self.model.pk])

    def test_legacy_shared_engine_migration_copies_machine_links_and_skips_deleted_fits(self):
        from automotive.models import EquipmentType, VehicleEngine
        make = VehicleMake.objects.create(name="Shared legacy maker")
        typ = EquipmentType.objects.create(name="Legacy pump kind")
        vehicle = VehicleModel.objects.create(make=make, name="Legacy pump", equipment_type=typ)
        engine = VehicleEngine.objects.create(engine_code="QA-shared")
        engine.fitted_models.add(vehicle)
        product = Product.objects.create(name="Shared-engine part")
        ProductFitment.objects.create(product=product, engine=engine)
        migrate = import_module("machinery.migrations.0002_separate_legacy_machines").migrate_machines
        migrate(apps, None)
        self.assertIn(product, MachineModel.objects.get(legacy_vehicle_model=vehicle).products.all())
        self.assertTrue(ProductFitment.objects.filter(product=product).exists())
