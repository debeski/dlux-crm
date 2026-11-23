from django.db import migrations, models
import django.db.models.functions.text


LIVE = models.Q(("deleted_at__isnull", True))


def _constraints():
    lower = django.db.models.functions.text.Lower
    return [
        ("machinetype", models.UniqueConstraint(lower("name"), models.F("scope"), condition=LIVE, name="machine_type_scoped_name")),
        ("machinetype", models.UniqueConstraint(lower("name"), condition=models.Q(("deleted_at__isnull", True), ("scope__isnull", True)), name="machine_type_global_name")),
        ("manufacturer", models.UniqueConstraint(lower("name"), models.F("scope"), condition=LIVE, name="machine_make_scoped_name")),
        ("manufacturer", models.UniqueConstraint(lower("name"), condition=models.Q(("deleted_at__isnull", True), ("scope__isnull", True)), name="machine_make_global_name")),
        ("machinemodel", models.UniqueConstraint(models.F("machine_type"), models.F("manufacturer"), lower("name"), condition=LIVE, name="machine_model_type_make_name")),
        ("machinemodel", models.UniqueConstraint(models.F("machine_type"), lower("name"), condition=models.Q(("deleted_at__isnull", True), ("manufacturer__isnull", True)), name="machine_model_type_name_no_make")),
    ]


class Migration(migrations.Migration):
    """Name uniqueness ignores soft-deleted rows, so a deleted machine type,
    manufacturer or model name can be added again."""

    dependencies = [("machinery", "0003_alter_machinemodel_manufacturer_and_more")]

    operations = [
        operation
        for model_name, constraint in _constraints()
        for operation in (
            migrations.RemoveConstraint(model_name=model_name, name=constraint.name),
            migrations.AddConstraint(model_name=model_name, constraint=constraint),
        )
    ]
