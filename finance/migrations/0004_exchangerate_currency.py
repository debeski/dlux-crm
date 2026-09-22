from decimal import Decimal

import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("finance", "0003_expensecategory_expense_staffaccount_and_more")]

    operations = [
        migrations.AddField(
            model_name="exchangerate",
            name="currency",
            field=models.CharField(
                choices=[("USD", "US Dollar (USD)"), ("EUR", "Euro (EUR)")],
                db_index=True,
                default="USD",
                max_length=3,
                verbose_name="Currency",
            ),
        ),
        migrations.AlterField(
            model_name="exchangerate",
            name="rate",
            field=models.DecimalField(
                decimal_places=4,
                help_text="How many Libyan Dinars equal one unit of the selected currency.",
                max_digits=12,
                validators=[django.core.validators.MinValueValidator(Decimal("0.0001"))],
                verbose_name="LYD per 1 unit",
            ),
        ),
    ]
