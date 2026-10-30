import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class UnsavedGuardTests(TestCase):
    """Modal forms arm DjangoLux's unsaved-changes prompt through the shared grid helper."""

    def setUp(self):
        from dlux.models import SystemSettings

        settings = SystemSettings.load()
        settings.is_configured = True
        settings.save(update_fields=["is_configured"])
        self.client.force_login(get_user_model().objects.create_superuser("guard", "guard@example.com", "x"))

    def test_scoped_modal_forms_carry_the_guard(self):
        for app_label, model_name in (("catalog", "product"), ("finance", "expensecategory"), ("sales", "customer")):
            with self.subTest(model=model_name):
                url = reverse("scoped_modal_manager", args=[app_label, model_name, "new"])
                response = self.client.get(url, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
                self.assertEqual(response.status_code, 200, url)
                self.assertIn("data-dlux-unsaved-guard", json.loads(response.content)["html"])

    def test_grid_helper_opts_the_form_in(self):
        from django import forms

        from common.forms import build_grid_helper

        form = forms.Form()
        build_grid_helper(form, [])
        self.assertIs(form.dlux_unsaved_guard, True)
