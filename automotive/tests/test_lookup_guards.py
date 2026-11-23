"""The till's vehicle panel asks the vehicle browser's permissions, bulk links
never cross stores, and the Vehicle Models tile counts what the browser offers."""
import json
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied
from django.test import RequestFactory, TestCase

from automotive.forms import BulkFitmentForm
from automotive.models import VehicleMake, VehicleModel
from automotive.tests.test_quick_fits import automotive_config
from catalog.models import Product
from common.access import crosses_scope
from machinery.forms import BulkMachineAssignmentForm
from machinery.models import MachineModel, MachineType
from sales.pos_views import POS_PERMS, VEHICLE_LOOKUP_PERMS, VehicleProductsView

User = get_user_model()
rf = RequestFactory()


def _user(name, *perms):
    user = User.objects.create_user(name, password="x")
    for code in perms:
        app_label, codename = code.split(".", 1)
        user.user_permissions.add(Permission.objects.get(content_type__app_label=app_label, codename=codename))
    return User.objects.get(pk=user.pk)


class TillVehicleLookupTests(TestCase):
    def _get(self, user):
        request = rf.get("/", {"make": "1"})
        request.user = user
        with patch("sales.pos_views.get_pos_config", return_value={"enabled": True, "receipt_size": "80"}), \
                patch("sales.pos_views._automotive_on", return_value=True):
            return VehicleProductsView.as_view()(request)

    def test_the_vehicle_panel_needs_the_vehicle_browser_permissions(self):
        with self.assertRaises(PermissionDenied):
            self._get(_user("cashier", *POS_PERMS))

    def test_the_panel_answers_with_the_browser_permissions(self):
        response = self._get(_user("seller", *POS_PERMS, *VEHICLE_LOOKUP_PERMS))
        self.assertEqual(response.status_code, 200)
        self.assertIn("items", json.loads(response.content))


class CrossScopeLinkTests(TestCase):
    def setUp(self):
        from dlux.models import Scope

        self.store_a = Scope.objects.create(name="Store A")
        self.store_b = Scope.objects.create(name="Store B")
        self.admin = User.objects.create_superuser("root", "root@example.com", "x")
        self.product = Product.objects.create(name="Seal", scope=self.store_a)

    def test_global_and_same_store_references_are_allowed(self):
        global_kind = MachineType.objects.create(name="Pump")
        own_kind = MachineType.objects.create(name="Mixer", scope=self.store_a)
        other_kind = MachineType.objects.create(name="Crane", scope=self.store_b)
        self.assertFalse(crosses_scope(self.product, global_kind, own_kind))
        self.assertTrue(crosses_scope(self.product, other_kind))

    def test_bulk_machine_assignment_refuses_another_stores_machine(self):
        kind = MachineType.objects.create(name="Pump", scope=self.store_b)
        machine = MachineModel.objects.create(machine_type=kind, name="F8", scope=self.store_b)
        form = BulkMachineAssignmentForm({"products": [self.product.pk], "machines": [machine.pk]}, user=self.admin)
        self.assertFalse(form.is_valid())
        self.assertIn("machines", form.errors)

    def test_bulk_fitment_refuses_another_stores_vehicle(self):
        make = VehicleMake.objects.create(name="Toyota", scope=self.store_b)
        model = VehicleModel.objects.create(make=make, name="Camry", scope=self.store_b)
        data = {"products": [self.product.pk], "fits": json.dumps([{"vehicle_model": model.pk, "year_from": 2012, "year_to": 2017}])}
        with automotive_config():
            form = BulkFitmentForm(data, user=self.admin)
            self.assertFalse(form.is_valid())
        self.assertIn("products", form.errors)


class VehicleModelTileTests(TestCase):
    def test_the_tile_counts_only_browsable_models(self):
        from common.views import WorkspaceDashboardView

        make = VehicleMake.objects.create(name="Toyota")
        VehicleModel.objects.create(make=make, name="Camry")
        VehicleModel.objects.create(make=make, name="Old", is_active=False)
        moved = VehicleModel.objects.create(make=make, name="F8")
        kind = MachineType.objects.create(name="Pump")
        MachineModel.objects.create(machine_type=kind, name="F8", legacy_vehicle_model=moved)
        retired_make = VehicleMake.objects.create(name="Retired", is_active=False)
        VehicleModel.objects.create(make=retired_make, name="Gone")

        from django.utils import timezone

        request = rf.get("/")
        request.user = User.objects.create_superuser("boss", "boss@example.com", "x")
        view = WorkspaceDashboardView()
        view.setup(request)
        with patch.object(WorkspaceDashboardView, "_till_open", return_value=False), \
                patch.object(WorkspaceDashboardView, "_browser_open", return_value=True), \
                patch.object(WorkspaceDashboardView, "_machine_browser_open", return_value=False):
            tiles = {tile["id"]: tile for tile in view._enhancement_tiles(timezone.localdate())}
        self.assertEqual(tiles["vehicle_browser"]["value"], "1")
