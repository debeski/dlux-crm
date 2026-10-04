from django.urls import path
from .views import MachineryHubView, MachineBrowserView, MachineTypeListView, ManufacturerListView, MachineModelListView, MachineSearchView
from .settings import machinery_enabled

app_name = "machinery"

class SidebarExclusion:
    def __bool__(self):
        return not machinery_enabled()

hub = MachineryHubView.as_view()
hub.sidebar_group = "machinery"
hub.sidebar_icon = "bi-gear-wide-connected"
hub.sidebar_permissions = ["machinery.view_machinemodel"]
hub.sidebar_exclude = SidebarExclusion()
browse = MachineBrowserView.as_view()
browse.sidebar_group = "workspace"
browse.sidebar_icon = "bi-gear-wide-connected"
browse.sidebar_permissions = list(MachineBrowserView.permission_required)
browse.sidebar_exclude = SidebarExclusion()
urlpatterns = [path("", hub, name="hub"), path("browse/", browse, name="browse")]
for route, view, name in [("types/", MachineTypeListView, "type_list"), ("manufacturers/", ManufacturerListView, "manufacturer_list"), ("models/", MachineModelListView, "model_list")]:
    callback = view.as_view()
    callback.sidebar_exclude = True
    urlpatterns.append(path(route, callback, name=name))

search = MachineSearchView.as_view()
search.sidebar_exclude = True
urlpatterns.append(path("models/search/", search, name="model_search"))

from .views import BulkMachineAssignmentView
bulk_assign = BulkMachineAssignmentView.as_view()
bulk_assign.sidebar_exclude = True
urlpatterns.append(path("assign/", bulk_assign, name="bulk_assign"))
