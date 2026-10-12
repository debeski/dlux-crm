"""Optional features' permissions leave the permission editors while off, and keep their grants."""
from contextlib import ExitStack, contextmanager
from unittest import mock, skipUnless

import dlux.access
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase

from common.permission_visibility import hidden_feature_permissions

HAS_HOOK = hasattr(dlux.access, "register_permission_visibility_filter")


@contextmanager
def switches(automotive=True, machinery=True, pos=True):
    with ExitStack() as stack:
        stack.enter_context(mock.patch("automotive.settings.automotive_enabled", return_value=automotive))
        stack.enter_context(mock.patch("machinery.settings.machinery_enabled", return_value=machinery))
        stack.enter_context(mock.patch("sales.pos_settings.get_pos_config", return_value={"enabled": pos}))
        yield


class HiddenFeaturePermissionsTests(TestCase):
    def hidden(self, **state):
        with switches(**state):
            condition = hidden_feature_permissions()
        return set() if condition is None else set(
            Permission.objects.filter(condition).values_list("content_type__app_label", "codename")
        )

    def test_everything_on_hides_nothing(self):
        self.assertEqual(self.hidden(), set())

    def test_each_switch_hides_only_its_own_permissions(self):
        vehicles = self.hidden(automotive=False)
        self.assertIn(("automotive", "view_vehiclemake"), vehicles)
        self.assertEqual({app for app, _codename in vehicles}, {"automotive"})

    def test_machinery_off(self):
        self.assertEqual({app for app, _codename in self.hidden(machinery=False)}, {"machinery"})

    def test_pos_off_hides_till_permissions_but_not_other_sales_ones(self):
        pos = self.hidden(pos=False)
        self.assertTrue({("sales", "use_pos"), ("sales", "pos_unlimited_discount"), ("sales", "view_possale")} <= pos)
        self.assertNotIn(("sales", "view_invoice"), pos)

    @skipUnless(HAS_HOOK, "DjangoLux without permission visibility filters")
    def test_group_keeps_hidden_grants_and_shows_them_again_when_switched_on(self):
        from django.contrib.auth.models import Group
        from dlux.forms import GroupPresetForm

        admin = get_user_model().objects.create_superuser("perm-admin", "a@example.com", "x")
        vehicles = Permission.objects.get(content_type__app_label="automotive", codename="view_vehiclemake")
        products = Permission.objects.get(content_type__app_label="catalog", codename="view_product")
        group = Group.objects.create(name="Counter")
        group.permissions.set([vehicles, products])

        with switches(automotive=False):
            form = GroupPresetForm(instance=group, user=admin)
            self.assertNotIn(vehicles, form.fields["permissions"].queryset)
            form = GroupPresetForm(
                data={"name": "Counter", "description": "", "scope": "", "permissions": [products.pk]},
                instance=group, user=admin,
            )
            self.assertTrue(form.is_valid(), form.errors)
            form.save()
        self.assertEqual(set(group.permissions.all()), {vehicles, products})

        with switches():
            form = GroupPresetForm(instance=group, user=admin)
        self.assertIn(vehicles, form.fields["permissions"].queryset)
        self.assertIn(vehicles, set(form.fields["permissions"].initial))
