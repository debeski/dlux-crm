from django import forms
from common.forms import build_grid_helper, translate_help_text
from common.i18n import t
from dlux.utils import set_field_attrs
from dlux.widgets import DluxMultipleChoiceSelectorWidget
from common.views import scope_filtered_queryset
from .models import MachineType, Manufacturer, MachineModel
from .settings import machinery_enabled


class ReferenceForm(forms.ModelForm):
    refresh_parent = True

    def __init__(self, *args, request=None, user=None, **kwargs):
        self.user = user or getattr(request, "user", None)
        super().__init__(*args, **kwargs)
        if self.user is not None and not self.instance.pk:
            from dlux.utils import get_user_scope, is_scope_enabled
            if is_scope_enabled():
                self.instance.scope = get_user_scope(self.user)
        for field in self.fields.values():
            if isinstance(field, (forms.ModelChoiceField, forms.ModelMultipleChoiceField)) and self.user is not None:
                field.queryset = scope_filtered_queryset(field.queryset, self.user)
        set_field_attrs(self)
        translate_help_text(self)
        rows = [("machine_type", "manufacturer"), ("name", "alias"), ("categories",), ("is_active",)] if "machine_type" in self.fields else [("name", "is_active")]
        build_grid_helper(self, rows)


class MachineTypeForm(ReferenceForm):
    class Meta:
        model = MachineType
        fields = ["name", "is_active"]


class ManufacturerForm(ReferenceForm):
    class Meta:
        model = Manufacturer
        fields = ["name", "is_active"]


class MachineModelForm(ReferenceForm):
    class Meta:
        model = MachineModel
        fields = ["machine_type", "manufacturer", "name", "alias", "categories", "is_active"]
        widgets = {"categories": DluxMultipleChoiceSelectorWidget(searchable=True, variant="list")}


    def clean_categories(self):
        categories = self.cleaned_data["categories"]
        if any(category.scope_id != self.instance.scope_id for category in categories):
            raise forms.ValidationError("Choose categories from the same scope.")
        return categories


def attach_machine_models(form, user, instance=None, request=None):
    if not machinery_enabled() or user is None or not user.has_perm("machinery.view_machinemodel"):
        return False
    qs = scope_filtered_queryset(MachineModel.objects.filter(is_active=True, machine_type__is_active=True, manufacturer__is_active=True), user).select_related("machine_type", "manufacturer")
    from dlux.utils import get_user_scope, is_scope_enabled
    target_scope = get_user_scope(user) if is_scope_enabled() else None
    target_scope_id = getattr(target_scope, "pk", None)
    if instance is not None and instance.pk:
        target_scope_id = instance.scope_id
    elif instance is None and form.is_bound:
        from catalog.models import Product
        raw = form.data.get(form.add_prefix("product"), "")
        products = scope_filtered_queryset(Product.objects.all(), user)
        existing = products.filter(pk=raw).first() if str(raw).isdecimal() else None
        if existing is not None:
            target_scope_id = existing.scope_id
    qs = qs.filter(scope_id=target_scope_id)
    form.fields["machine_models"] = forms.ModelMultipleChoiceField(
        queryset=qs, required=False, label=t("machine_compatibility", "Compatible machines"), widget=DluxMultipleChoiceSelectorWidget(searchable=True, variant="list"),
    )
    if instance is not None and instance.pk:
        form.initial["machine_models"] = list(instance.machine_models.values_list("pk", flat=True))
    elif request is not None:
        category = request.GET.get("category", "")
        if "category" in form.fields and category.isdecimal() and form.fields["category"].queryset.filter(pk=category).exists():
            form.initial["category"] = category
        selected = request.GET.get("machine_model")
        if selected and selected.isdecimal() and qs.filter(pk=selected).exists():
            form.initial["machine_models"] = [selected]
    return True


def save_machine_models(form, instance):
    if "machine_models" in form.fields:
        visible = form.fields["machine_models"].queryset
        instance.machine_models.remove(*visible.filter(pk__in=instance.machine_models.values("pk")))
        instance.machine_models.add(*form.cleaned_data["machine_models"])


class BulkMachineAssignmentForm(forms.Form):
    products = forms.ModelMultipleChoiceField(queryset=None)
    machines = forms.ModelMultipleChoiceField(queryset=None)

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        from catalog.models import Product
        self.fields["products"].queryset = scope_filtered_queryset(Product.objects.filter(is_active=True), user).order_by("name")
        self.fields["machines"].queryset = scope_filtered_queryset(MachineModel.objects.filter(is_active=True, machine_type__is_active=True, manufacturer__is_active=True), user)
        self.fields["products"].label = t("models_product", "Products")
        self.fields["machines"].label = t("machine_compatibility", "Compatible machines")
        for field in self.fields.values():
            field.widget = DluxMultipleChoiceSelectorWidget(variant="searchable-list", searchable=True)
            field.widget.choices = field.choices
        set_field_attrs(self)
        build_grid_helper(self, [("products",), ("machines",)])
