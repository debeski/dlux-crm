from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.db import transaction
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View
from django.views.generic import TemplateView

from dlux.utils import log_user_action
from dlux.views import DynamicModalDeleteView, DynamicModalManagerView

from catalog.models import Product
from common.i18n import t
from common.views import RibbonPageMixin, ScopedListView, scope_filtered_queryset
from finance.services import get_current_rate

from .browser import VehicleBrowser
from .filters import (
    VehicleEngineFilter,
    VehicleGenerationFilter,
    VehicleMakeFilter,
    VehicleModelFilter,
    VehicleTrimFilter,
)
from .forms import ProductFitmentFormSet
from .models import VehicleEngine, VehicleGeneration, VehicleMake, VehicleModel, VehicleTrim
from .settings import get_automotive_config
from .tables import (
    VehicleEngineTable,
    VehicleGenerationTable,
    VehicleMakeTable,
    VehicleModelTable,
    VehicleTrimTable,
)


class AutomotiveEnabledMixin:
    automotive_criterion = None

    def dispatch(self, request, *args, **kwargs):
        config = get_automotive_config()
        if not config["enabled"]:
            raise Http404
        if self.automotive_criterion and not config["criteria"][self.automotive_criterion]:
            raise Http404
        return super().dispatch(request, *args, **kwargs)


class OptionalEnhancementModalGuardMixin:
    def dispatch(self, request, *args, **kwargs):
        if kwargs.get("app_label") == "automotive":
            config = get_automotive_config()
            model_name = kwargs.get("model_name", "").lower()
            criterion_by_model = {
                "vehiclegeneration": "generation_chassis",
                "vehicleengine": "engine",
                "vehicletrim": "trim",
            }
            if (
                not config["enabled"]
                or model_name == "productfitment"
                or (
                    model_name in criterion_by_model
                    and not config["criteria"][criterion_by_model[model_name]]
                )
            ):
                raise Http404
        return super().dispatch(request, *args, **kwargs)


class FeatureAwareDynamicModalManagerView(
    OptionalEnhancementModalGuardMixin,
    DynamicModalManagerView,
):
    pass


class FeatureAwareDynamicModalDeleteView(
    OptionalEnhancementModalGuardMixin,
    DynamicModalDeleteView,
):
    pass


class AutomotiveHubView(
    AutomotiveEnabledMixin,
    RibbonPageMixin,
    LoginRequiredMixin,
    PermissionRequiredMixin,
    TemplateView,
):
    permission_required = "automotive.view_vehiclemake"
    raise_exception = True
    template_name = "automotive/hub.html"
    page_title_key = "page_automotive_data"
    page_subtitle_key = "page_automotive_data_sub"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["automotive_config"] = get_automotive_config()
        return context


class VehicleBrowserView(
    AutomotiveEnabledMixin,
    RibbonPageMixin,
    LoginRequiredMixin,
    PermissionRequiredMixin,
    TemplateView,
):
    permission_required = (
        "automotive.view_vehiclemake",
        "automotive.view_vehiclemodel",
        "automotive.view_productfitment",
        "catalog.view_product",
    )
    raise_exception = True
    template_name = "automotive/browser.html"
    page_title_key = "page_vehicle_browser"
    page_subtitle_key = "page_vehicle_browser_sub"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(VehicleBrowser(self.request, get_automotive_config()).build())
        rate = get_current_rate()
        for product in context["products"]:
            product.browser_price_lyd = product.selling_price_lyd(rate)
        context["extra_styles"] = ["automotive/css/browser.css", "catalog/css/product_card.css"]
        return context


class AutomotiveListView(AutomotiveEnabledMixin, ScopedListView):
    extra_scripts = ("automotive/js/dependent_selects.js",)


class VehicleMakeListView(AutomotiveListView):
    model = VehicleMake
    permission_required = "automotive.view_vehiclemake"
    table_class = VehicleMakeTable
    filterset_class = VehicleMakeFilter
    page_title_key = "page_vehicle_makes"
    page_subtitle_key = "page_vehicle_makes_sub"


class VehicleModelListView(AutomotiveListView):
    model = VehicleModel
    permission_required = "automotive.view_vehiclemodel"
    table_class = VehicleModelTable
    filterset_class = VehicleModelFilter
    page_title_key = "page_vehicle_models"
    page_subtitle_key = "page_vehicle_models_sub"

    def get_queryset(self):
        return super().get_queryset().select_related("make")


class VehicleGenerationListView(AutomotiveListView):
    automotive_criterion = "generation_chassis"
    model = VehicleGeneration
    permission_required = "automotive.view_vehiclegeneration"
    table_class = VehicleGenerationTable
    filterset_class = VehicleGenerationFilter
    page_title_key = "page_vehicle_generations"
    page_subtitle_key = "page_vehicle_generations_sub"

    def get_queryset(self):
        return super().get_queryset().select_related("vehicle_model", "vehicle_model__make")


class VehicleEngineListView(AutomotiveListView):
    automotive_criterion = "engine"
    model = VehicleEngine
    permission_required = "automotive.view_vehicleengine"
    table_class = VehicleEngineTable
    filterset_class = VehicleEngineFilter
    page_title_key = "page_vehicle_engines"
    page_subtitle_key = "page_vehicle_engines_sub"

    def get_queryset(self):
        return super().get_queryset().select_related(
            "vehicle_model", "vehicle_model__make", "generation",
        )

    @property
    def ribbon_advanced(self):
        fields = ["is_active"]
        if get_automotive_config()["criteria"]["fuel_type"]:
            fields.insert(0, "fuel_type")
        return fields

    def get_table_kwargs(self):
        kwargs = super().get_table_kwargs()
        criteria = get_automotive_config()["criteria"]
        excluded = []
        if not criteria["generation_chassis"]:
            excluded.append("generation")
        if not criteria["fuel_type"]:
            excluded.append("fuel_type")
        if excluded:
            kwargs["exclude"] = excluded
        return kwargs


class VehicleTrimListView(AutomotiveListView):
    automotive_criterion = "trim"
    model = VehicleTrim
    permission_required = "automotive.view_vehicletrim"
    table_class = VehicleTrimTable
    filterset_class = VehicleTrimFilter
    page_title_key = "page_vehicle_trims"
    page_subtitle_key = "page_vehicle_trims_sub"

    def get_queryset(self):
        return super().get_queryset().select_related(
            "vehicle_model", "vehicle_model__make", "generation",
        )

    def get_table_kwargs(self):
        kwargs = super().get_table_kwargs()
        if not get_automotive_config()["criteria"]["generation_chassis"]:
            kwargs["exclude"] = ["generation"]
        return kwargs


class ProductFitmentEditorView(
    AutomotiveEnabledMixin,
    RibbonPageMixin,
    LoginRequiredMixin,
    PermissionRequiredMixin,
    View,
):
    permission_required = (
        "automotive.view_productfitment",
        "automotive.add_productfitment",
        "automotive.change_productfitment",
        "automotive.delete_productfitment",
    )
    raise_exception = True
    template_name = "automotive/product_fitments.html"
    page_title_key = "ui_manage_fitments"
    page_subtitle_key = "fitment_editor_help"

    def get_ribbon_action_specs(self):
        return [{
            "label": t("btn_back", "Back"),
            "icon": "bi bi-arrow-left",
            "url": reverse("catalog:product_list"),
            "css_class": "btn btn-outline-secondary rounded-pill",
        }]

    def get_product(self):
        queryset = scope_filtered_queryset(Product.objects.select_related("category"), self.request.user)
        return get_object_or_404(queryset, pk=self.kwargs["pk"])

    def get_formset(self, product, data=None):
        config = get_automotive_config()
        return ProductFitmentFormSet(
            data=data,
            instance=product,
            prefix="fitments",
            criteria=config["criteria"],
            confirm_overlaps=(data or {}).get("confirm_overlaps") == "1",
            request=self.request,
            user=self.request.user,
            queryset=product.automotive_fitments.select_related(
                "vehicle_model", "vehicle_model__make", "generation", "engine", "trim",
            ).all(),
        )

    def context(self, product, formset):
        config = get_automotive_config()
        context = {
            "product": product,
            "formset": formset,
            "criteria": config["criteria"],
            "confirm_overlaps": self.request.POST.get("confirm_overlaps") == "1",
        }
        context["ribbon"] = self.get_ribbon(context)
        return context

    def get(self, request, pk):
        product = self.get_product()
        return render(request, self.template_name, self.context(product, self.get_formset(product)))

    def post(self, request, pk):
        product = self.get_product()
        formset = self.get_formset(product, request.POST)
        if not formset.is_valid():
            return render(request, self.template_name, self.context(product, formset), status=400)

        with transaction.atomic():
            objects = formset.save(commit=False)
            for deleted in formset.deleted_objects:
                deleted.delete()
            for fitment in objects:
                fitment.product = product
                fitment.scope = product.scope
                fitment.save()
            formset.save_m2m()
            log_user_action(request, "UPDATE", instance=product)
        messages.success(request, "Vehicle compatibility saved.")
        return redirect("catalog:product_list")


class AutomotiveDependenciesView(
    AutomotiveEnabledMixin,
    LoginRequiredMixin,
    PermissionRequiredMixin,
    View,
):
    permission_required = "automotive.view_vehiclemodel"
    raise_exception = True

    def get(self, request):
        config = get_automotive_config()["criteria"]
        models = scope_filtered_queryset(
            VehicleModel.objects.filter(is_active=True, make__is_active=True).select_related("make"),
            request.user,
        )
        generations = scope_filtered_queryset(
            VehicleGeneration.objects.filter(is_active=True).select_related("vehicle_model"),
            request.user,
        )
        engines = scope_filtered_queryset(
            VehicleEngine.objects.filter(is_active=True).select_related("generation"),
            request.user,
        )
        trims = scope_filtered_queryset(
            VehicleTrim.objects.filter(is_active=True).select_related("generation"),
            request.user,
        )
        if not config["generation_chassis"]:
            engines = engines.filter(generation__isnull=True)
            trims = trims.filter(generation__isnull=True)
        return JsonResponse({
            "models": [
                {"id": item.pk, "label": str(item), "make_id": item.make_id}
                for item in models.order_by("make__name", "name")
            ],
            "generations": [
                {"id": item.pk, "label": str(item), "model_id": item.vehicle_model_id}
                for item in generations.order_by("year_from", "name")
            ] if config["generation_chassis"] else [],
            "engines": [
                {
                    "id": item.pk,
                    "label": str(item),
                    "model_id": item.vehicle_model_id,
                    "generation_id": item.generation_id,
                }
                for item in engines.order_by("display_name", "engine_code")
            ] if config["engine"] else [],
            "trims": [
                {
                    "id": item.pk,
                    "label": str(item),
                    "model_id": item.vehicle_model_id,
                    "generation_id": item.generation_id,
                }
                for item in trims.order_by("name")
            ] if config["trim"] else [],
        })
