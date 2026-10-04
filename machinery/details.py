from dlux.middleware import get_current_user
from common.views import scope_filtered_queryset
from common.i18n import t
from .settings import machinery_enabled


def compatibility_detail(instance):
    user = get_current_user()
    if not machinery_enabled() or user is None or not user.has_perm("machinery.view_machinemodel"):
        return None
    machines = scope_filtered_queryset(instance.machine_models.select_related("machine_type", "manufacturer"), user)
    labels = [str(machine) for machine in machines]
    return {"label": t("machine_compatibility", "Compatible machines"), "value": "; ".join(labels)} if labels else None
