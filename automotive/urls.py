from django.urls import path

from .views import (
    AutomotiveDependenciesView,
    AutomotiveHubView,
    BulkFitmentView,
    FitsSourceView,
    ProductFitmentEditorView,
    VehicleEngineListView,
    VehicleGenerationListView,
    VehicleMakeListView,
    VehicleModelListView,
    VehicleTrimListView,
    VehicleBrowserView,
    VehicleSearchView,
)
from .settings import automotive_enabled

app_name = "automotive"


class _AutomotiveSidebarExclusion:
    def __bool__(self):
        return not automotive_enabled()


_hub = AutomotiveHubView.as_view()
_hub.sidebar_group = "automotive"
_hub.sidebar_icon = "bi-car-front"
_hub.sidebar_permissions = ["automotive.view_vehiclemake"]
_hub.sidebar_exclude = _AutomotiveSidebarExclusion()
_browse = VehicleBrowserView.as_view()
_browse.sidebar_group = "workspace"
_browse.sidebar_icon = "bi-car-front-fill"
_browse.sidebar_permissions = list(VehicleBrowserView.permission_required)
_browse.sidebar_exclude = _AutomotiveSidebarExclusion()
_makes = VehicleMakeListView.as_view()
_makes.sidebar_exclude = True
_models = VehicleModelListView.as_view()
_models.sidebar_exclude = True
_generations = VehicleGenerationListView.as_view()
_generations.sidebar_exclude = True
_engines = VehicleEngineListView.as_view()
_engines.sidebar_exclude = True
_trims = VehicleTrimListView.as_view()
_trims.sidebar_exclude = True
_fitments = ProductFitmentEditorView.as_view()
_fitments.sidebar_exclude = True
_dependencies = AutomotiveDependenciesView.as_view()
_dependencies.sidebar_exclude = True
_vehicle_search = VehicleSearchView.as_view()
_vehicle_search.sidebar_exclude = True
_fits_source = FitsSourceView.as_view()
_fits_source.sidebar_exclude = True
_bulk_fitments = BulkFitmentView.as_view()
_bulk_fitments.sidebar_exclude = True

urlpatterns = [
    path("", _hub, name="hub"),
    path("browse/", _browse, name="browse"),
    path("makes/", _makes, name="make_list"),
    path("models/", _models, name="model_list"),
    path("generations/", _generations, name="generation_list"),
    path("engines/", _engines, name="engine_list"),
    path("trims/", _trims, name="trim_list"),
    path("products/<int:pk>/fitments/", _fitments, name="product_fitments"),
    path("dependencies/", _dependencies, name="dependencies"),
    path("vehicles/search/", _vehicle_search, name="vehicle_search"),
    path("fits/source/", _fits_source, name="fits_source"),
    path("fits/bulk/", _bulk_fitments, name="bulk_fitments"),
]
