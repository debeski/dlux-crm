from urllib.parse import urlencode
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.http import Http404, JsonResponse
from django.urls import reverse
from django.views.generic import TemplateView
from django.views import View
from django.db.models import Q
from dlux.tables import DluxTable
from common.i18n import t
from .filters import MachineTypeFilter, ManufacturerFilter, MachineModelFilter
from common.tables import ModalRowActionsMixin
from common.views import ScopedListView, RibbonPageMixin, scope_filtered_queryset
from catalog.models import Category, Product, Service
from .models import MachineType, Manufacturer, MachineModel
from .settings import machinery_enabled


class MachineryEnabledMixin:
    def dispatch(self, request, *args, **kwargs):
        if not machinery_enabled():
            raise Http404
        return super().dispatch(request, *args, **kwargs)


class MachineTypeTable(ModalRowActionsMixin, DluxTable):
    row_delete_action = False
    class Meta(DluxTable.Meta):
        model = MachineType
        fields = ("name", "is_active")
        dlux_actions = True


class ManufacturerTable(ModalRowActionsMixin, DluxTable):
    row_delete_action = False
    class Meta(DluxTable.Meta):
        model = Manufacturer
        fields = ("name", "is_active")
        dlux_actions = True


class MachineModelTable(ModalRowActionsMixin, DluxTable):
    row_delete_action = False
    class Meta(DluxTable.Meta):
        model = MachineModel
        fields = ("machine_type", "manufacturer", "name", "alias", "is_active")
        dlux_actions = True


class MachineTypeListView(MachineryEnabledMixin, ScopedListView):
    model = MachineType
    filterset_class = MachineTypeFilter
    table_class = MachineTypeTable
    permission_required = "machinery.view_machinetype"
    page_title_key = "models_machinetype"


class ManufacturerListView(MachineryEnabledMixin, ScopedListView):
    model = Manufacturer
    filterset_class = ManufacturerFilter
    table_class = ManufacturerTable
    permission_required = "machinery.view_manufacturer"
    page_title_key = "models_manufacturer"


class MachineModelListView(MachineryEnabledMixin, ScopedListView):
    model = MachineModel
    filterset_class = MachineModelFilter
    table_class = MachineModelTable
    permission_required = "machinery.view_machinemodel"
    page_title_key = "models_machinemodel"


class MachineryHubView(MachineryEnabledMixin, RibbonPageMixin, LoginRequiredMixin, PermissionRequiredMixin, TemplateView):
    permission_required = "machinery.view_machinemodel"
    template_name = "machinery/hub.html"
    page_title_key = "page_machinery"
    page_subtitle_key = "page_machinery_sub"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        specs = [
            ("machinery:browse", "Browse machinery", "machinery.view_machinemodel"),
            ("machinery:type_list", "Machine types", "machinery.view_machinetype"),
            ("machinery:manufacturer_list", "Manufacturers", "machinery.view_manufacturer"),
            ("machinery:model_list", "Machine models", "machinery.view_machinemodel"),
            ("catalog:category_list", "Category branches", "catalog.view_category"),
            ("catalog:product_list", "Parts", "catalog.view_product"),
            ("catalog:service_list", "Services", "catalog.view_service"),
        ]
        ctx["links"] = [(reverse(url), t({"Browse machinery": "page_machine_browser", "Machine types": "models_machinetype", "Manufacturers": "models_manufacturer", "Machine models": "models_machinemodel", "Category branches": "label_machinemodel_categories", "Parts": "models_product", "Services": "models_service"}[label], label)) for url, label, perm in specs if self.request.user.has_perm(perm)]
        icons = ["bi-search", "bi-grid-3x3-gap", "bi-buildings", "bi-gear-wide-connected", "bi-diagram-3", "bi-box-seam", "bi-tools"]
        ctx["hub_cards"] = []
        for (route, label, permission), icon in zip(specs, icons):
            if self.request.user.has_perm(permission):
                title = next(title for url, title in ctx["links"] if url == reverse(route))
                ctx["hub_cards"].append({"route": route, "title": title, "icon": "bi " + icon, "description": t("machine_hub_" + route.split(":")[-1], label), "border": "border-primary" if route == "machinery:browse" else "border-0"})
        return ctx


class MachineBrowserView(MachineryEnabledMixin, RibbonPageMixin, LoginRequiredMixin, PermissionRequiredMixin, TemplateView):
    permission_required = ("machinery.view_machinetype", "machinery.view_manufacturer", "machinery.view_machinemodel")
    template_name = "machinery/browser.html"
    page_title_key = "page_machine_browser"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        def scoped(qs):
            return scope_filtered_queryset(qs, user)
        def selected(qs, key):
            raw = self.request.GET.get(key, "")
            return qs.filter(pk=raw).first() if raw.isdecimal() else None
        def link(**params):
            return "?" + urlencode({k: v for k, v in params.items() if v is not None})
        types = scoped(MachineType.objects.filter(is_active=True))
        typ = selected(types, "type")
        makers = scoped(Manufacturer.objects.filter(is_active=True, machinemodel__machine_type=typ, machinemodel__is_active=True)).distinct() if typ else Manufacturer.objects.none()
        maker = selected(makers, "manufacturer")
        models = scoped(MachineModel.objects.filter(is_active=True, machine_type=typ, manufacturer=maker)).select_related("machine_type", "manufacturer") if maker else MachineModel.objects.none()
        model = selected(models, "model")
        categories = scoped(Category.objects.filter(is_active=True)).select_related("parent")
        query = self.request.GET.get("q", "").strip()
        products = scoped(Product.objects.filter(is_active=True, machine_models__is_active=True, machine_models__machine_type__is_active=True, machine_models__manufacturer__is_active=True)) if (model or query) and user.has_perm("catalog.view_product") else Product.objects.none()
        if model:
            products = products.filter(machine_models=model)
        elif query:
            products = products.filter(machine_models__in=scoped(MachineModel.objects.filter(is_active=True)))
        services = scoped(Service.objects.filter(is_active=True, machine_models=model)) if model and user.has_perm("catalog.view_service") else Service.objects.none()
        allowed = set()
        if model:
            seeds = set(model.categories.values_list("pk", flat=True)) | set(products.values_list("category_id", flat=True)) | set(services.values_list("category_id", flat=True))
            by_id = {c.pk: c for c in categories}
            for pk in seeds:
                node = by_id.get(pk)
                while node and node.pk not in allowed:
                    allowed.add(node.pk)
                    node = by_id.get(node.parent_id)
            for pk in model.categories.values_list("pk", flat=True):
                if pk in by_id:
                    allowed.update(by_id[pk].descendant_ids(categories))
        category = selected(categories.filter(pk__in=allowed), "category")
        base = dict(type=typ.pk if typ else None, manufacturer=maker.pk if maker else None, model=model.pk if model else None)
        breadcrumbs = [(t("models_machinetype", "Machine types"), "?")]
        if typ: breadcrumbs.append((str(typ), link(type=typ.pk)))
        if maker: breadcrumbs.append((str(maker), link(type=typ.pk, manufacturer=maker.pk)))
        if model: breadcrumbs.append((model.name, link(**base)))
        ancestors, current = [], category
        while current:
            ancestors.append(current)
            current = current.parent
        for node in reversed(ancestors):
            breadcrumbs.append((node.name, link(**base, category=node.pk)))
        choices = []
        if not typ:
            choices = [(str(obj), link(type=obj.pk)) for obj in types]
        elif not maker:
            choices = [(str(obj), link(type=typ.pk, manufacturer=obj.pk)) for obj in makers]
        elif not model:
            choices = [(obj.name + (f" · {obj.alias}" if obj.alias else ""), link(type=typ.pk, manufacturer=maker.pk, model=obj.pk)) for obj in models]
        else:
            choices = [(obj.name, link(**base, category=obj.pk)) for obj in categories.filter(pk__in=allowed, parent=category)]
        if category:
            descendants = category.descendant_ids(categories)
            products = products.filter(category_id__in=descendants)
            services = services.filter(category_id__in=descendants)
        query = self.request.GET.get("q", "").strip()
        if query:
            products = products.filter(Q(name__icontains=query) | Q(alias__icontains=query) | Q(sku__icontains=query) | Q(barcode__icontains=query) | Q(extra_barcodes__code__icontains=query))
            services = services.filter(name__icontains=query)
        entries = []
        for kind, qs in (("product", products), ("service", services)):
            for obj in qs.distinct().select_related("category"):
                obj.browser_price_lyd = obj.selling_price_lyd()
                entries.append({"object": obj, "name": obj.name, "alias": getattr(obj, "alias", ""), "category": str(obj.category) if obj.category_id else "", "price": obj.selling_price_lyd(), "service": kind == "service", "url": reverse("scoped_modal_manager", args=["catalog", kind, obj.pk]) + "?action=view"})
        adds = []
        if model:
            for kind in ("product", "service"):
                if user.has_perm(f"catalog.add_{kind}") and not (kind == "product" and category and category.is_service):
                    adds.append((kind, reverse("scoped_modal_manager", args=["catalog", kind, "new"]) + "?" + urlencode({"machine_model": model.pk, "category": category.pk if category else ""})))
        step_number, step_key = (1, "machine_choose_type") if not typ else (2, "machine_choose_manufacturer") if not maker else (3, "vehicle_choose_model") if not model else (4, "models_category")
        ctx.update(choices=choices, breadcrumbs=breadcrumbs, entries=entries, model=model, query=query, adds=adds, selected_params=base, category=category,
                   step_number=step_number, step_title=t(step_key, "Categories"), show_results=bool(model or query), machine_search_url=reverse("machinery:model_search"))
        return ctx


class MachineSearchView(MachineryEnabledMixin, LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = MachineBrowserView.permission_required

    def get(self, request):
        query = request.GET.get("q", "").strip()
        if len(query) < 2:
            return JsonResponse({"results": []})
        models = scope_filtered_queryset(MachineModel.objects.filter(is_active=True, machine_type__is_active=True, manufacturer__is_active=True), request.user).select_related("machine_type", "manufacturer")
        for word in query.split():
            models = models.filter(Q(name__icontains=word) | Q(alias__icontains=word) | Q(manufacturer__name__icontains=word) | Q(machine_type__name__icontains=word))
        return JsonResponse({"results": [{"label": str(model) + (f" · {model.alias}" if model.alias else ""), "browse_params": {"type": model.machine_type_id, "manufacturer": model.manufacturer_id, "model": model.pk}} for model in models[:20]]})


class BulkMachineAssignmentView(MachineryEnabledMixin, LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = ("catalog.view_product", "catalog.change_product", "machinery.view_machinemodel")
    raise_exception = True

    def render_modal(self, form):
        from django.template.loader import render_to_string
        return render_to_string("automotive/bulk_fitments.html", {"form": form, "assignment_url": reverse("machinery:bulk_assign"), "assignment_help": t("machine_bulk_help", "Choose products and machines. Existing compatibility is kept."), "assignment_label": t("machine_assign", "Assign machines"), "assignment_icon": "bi-gear-wide-connected"}, request=self.request)

    def get(self, request):
        from .forms import BulkMachineAssignmentForm
        return JsonResponse({"html": self.render_modal(BulkMachineAssignmentForm(user=request.user))})

    def post(self, request):
        from django.db import transaction
        from .forms import BulkMachineAssignmentForm
        form = BulkMachineAssignmentForm(request.POST, user=request.user)
        if not form.is_valid():
            return JsonResponse({"success": False, "html": self.render_modal(form)})
        from dlux.utils import log_user_action
        with transaction.atomic():
            for product in form.cleaned_data["products"]:
                product.machine_models.add(*form.cleaned_data["machines"])
                log_user_action(request, "UPDATE", instance=product)
        return JsonResponse({"success": True, "refresh_parent": True})
