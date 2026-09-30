from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.cache import cache
from django.test import Client, TestCase
from django.urls import reverse

from dlux.models import SystemSettings
from dlux.options import write_app_system_config


User = get_user_model()
PASSWORD = "Landing-pass-123!"


class LoginLandingTests(TestCase):
    """Where a user lands after signing in is DjangoLux's Home setting alone.

    Enabling the till or parts mode must not redirect anyone; a store that wants
    its counter to open on the till sets Home to it.
    """

    def setUp(self):
        settings = SystemSettings.load()
        settings.is_configured = True
        settings.save(update_fields=["is_configured"])
        # Saved settings are cached; the test's rollback does not reach the cache.
        self.addCleanup(cache.clear)
        write_app_system_config("switch_pos.point_of_sale", {"enabled": True})
        write_app_system_config("switch_pos.optional_enhancements", {"automotive": {"enabled": True}})
        self.seller = User.objects.create_user("counter-seller", password=PASSWORD)
        self.seller.user_permissions.add(*Permission.objects.filter(
            content_type__app_label__in=["sales", "catalog", "automotive"],
            codename__in=["use_pos", "add_invoice", "issue_invoice", "add_payment", "view_product", "view_productfitment"],
        ))

    def sign_in(self):
        client = Client()
        response = client.post(reverse("login"), {"username": "counter-seller", "password": PASSWORD})
        self.assertEqual(response.status_code, 302)
        return client, response["Location"]

    def test_the_till_and_parts_mode_do_not_redirect_a_login(self):
        client, landing = self.sign_in()
        self.assertEqual(landing, "/staff/workspace/")
        self.assertRedirects(client.get("/staff/"), reverse("common:workspace_dashboard"), fetch_redirect_response=False)

    def test_home_set_to_the_till_opens_it_after_login(self):
        settings = SystemSettings.load()
        settings.homepage_config = {**(settings.homepage_config or {}), "default_url": reverse("sales:pos_till")}
        settings.save()
        cache.clear()
        client, landing = self.sign_in()
        self.assertEqual(landing, reverse("sales:pos_till"))
        self.assertEqual(client.get(landing).status_code, 200)
