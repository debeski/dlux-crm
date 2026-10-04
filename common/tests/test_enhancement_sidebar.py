from copy import deepcopy
from unittest.mock import patch
from django.test import RequestFactory, SimpleTestCase
from common.context_processors import crm_context


class EnhancementSidebarTests(SimpleTestCase):
    def setUp(self):
        self.entries = [
            {"kind": "item", "url_name": "automotive:hub", "url": "/staff/automotive/"},
            {"kind": "group", "id": "vehicles", "items": [{"kind": "item", "url_name": "automotive:browse", "url": "/staff/automotive/browse/"}]},
            {"kind": "item", "url_name": "machinery:hub", "url": "/staff/machinery/"},
            {"kind": "item", "url_name": "catalog:product_list", "url": "/staff/catalog/products/"},
        ]
        self.context = {key: deepcopy(self.entries) for key in ("sidebar_entries", "sidebar_tree_state", "sidebar_auto_items", "sidebar_extra_groups")}
        self.context["sidebar"] = {"enabled": True, "entries": deepcopy(self.entries)}

    def render(self, vehicle, machine):
        with patch("dlux.context_processors.dlux_context", return_value=self.context), patch("automotive.settings.get_optional_enhancements_config", return_value={"automotive": {"enabled": vehicle}, "machinery": {"enabled": machine}}):
            return crm_context(RequestFactory().get("/staff/workspace/"))

    def test_disabled_vehicle_hides_saved_links_and_empty_groups_in_all_sidebar_surfaces(self):
        context = self.render(False, True)
        for key in ("sidebar_entries", "sidebar_tree_state", "sidebar_auto_items", "sidebar_extra_groups"):
            self.assertEqual([item["url_name"] for item in context[key]], ["machinery:hub", "catalog:product_list"])
        self.assertEqual(context["sidebar"]["entries"], context["sidebar_entries"])
        self.assertEqual(len(self.context["sidebar_entries"]), 4)

    def test_reenable_restores_saved_order_without_resetting_layout(self):
        self.render(False, True)
        self.assertEqual(self.render(True, True)["sidebar_entries"], self.entries)

    def test_machinery_switch_is_independent(self):
        context = self.render(True, False)
        self.assertEqual(len(context["sidebar_entries"]), 3)
        self.assertEqual(context["sidebar_entries"][0]["url_name"], "automotive:hub")

    def test_saved_direct_vehicle_url_is_hidden(self):
        self.context["sidebar_entries"].append({"kind": "item", "url": "/staff/automotive/models/"})
        self.assertEqual(len(self.render(False, True)["sidebar_entries"]), 2)
