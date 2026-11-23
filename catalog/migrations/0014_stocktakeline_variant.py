import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """A stock-take line counts one colour/size bucket (or the stock a product
    holds outside its buckets), so applying a take moves the buckets too."""

    dependencies = [("catalog", "0013_opening_stock_draft")]

    operations = [
        migrations.AddField(
            model_name="stocktakeline",
            name="variant",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name="stock_take_lines", to="catalog.productvariant", verbose_name="Variant",
            ),
        ),
        migrations.RemoveConstraint(model_name="stocktakeline", name="uniq_stocktake_product"),
        migrations.AddConstraint(
            model_name="stocktakeline",
            constraint=models.UniqueConstraint(fields=("stock_take", "product", "variant"), name="uniq_stocktake_bucket"),
        ),
        migrations.AddConstraint(
            model_name="stocktakeline",
            constraint=models.UniqueConstraint(
                condition=models.Q(("variant__isnull", True)), fields=("stock_take", "product"),
                name="uniq_stocktake_product_unbucketed",
            ),
        ),
        migrations.AlterModelOptions(
            name="stocktakeline",
            options={
                "default_permissions": (),
                "ordering": ["product__name", "variant__color", "variant__size", "variant_id"],
                "verbose_name": "Stock Take Line",
                "verbose_name_plural": "Stock Take Lines",
            },
        ),
    ]
