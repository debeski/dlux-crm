"""
Create the project's permission groups so the owner doesn't have to tick boxes.

Row-level visibility (see ``common.access``) means the *same* view permission
behaves differently per group: a rep with ``view_invoice`` sees only their own
sales, while a manager who additionally holds ``view_all_invoice`` sees the whole
store. So the three roles differ mostly by their ``view_all_*`` / ``assign_*``
grants:

  * "Sales Manager"        — sees & assigns everyone's work, runs reports, manages
                             the catalog + exchange rate, confirms cash deposits.
  * "Sales Representative"  — sells: creates/issues invoices, takes payments, keeps
                             their OWN customer book. No view_all → own data only.
  * "Delivery Courier"      — sees only deliveries assigned to them and records the
                             cash they collect. No access to invoices or reports.

Admins are expected to be Django superusers (full access).

Run:  python manage.py seed_roles
Idempotent — safe to re-run after adding models/permissions.
"""
from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand

# Sells only their own work (no view_all_* → row-scoped to themselves).
REP_PERMS = [
    "sales.view_invoice",
    "sales.add_invoice",
    "sales.change_invoice",      # edit own drafts before issuing
    "sales.issue_invoice",
    "sales.view_payment",
    "sales.add_payment",
    "sales.view_customer",
    "sales.add_customer",
    "sales.change_customer",
    # Look up what to sell (read-only)
    "catalog.view_product",
    "catalog.view_service",
    "automotive.view_vehiclemake",
    "automotive.view_vehiclemodel",
    "automotive.view_vehiclegeneration",
    "automotive.view_vehicleengine",
    "automotive.view_vehicletrim",
    "automotive.view_productfitment",
    # Hand over the cash they collected (an admin/manager confirms it)
    "finance.view_cashdeposit",
    "finance.add_cashdeposit",
    # Own staff account: advances, loans, commissions, service payouts
    "finance.view_staffaccount",
    "finance.view_staffledgerentry",
]

# Only the deliveries assigned to them (no view_all_delivery). Never sees sales.
COURIER_PERMS = [
    "sales.view_delivery",
    "sales.change_delivery",     # update status of their own jobs
    "finance.view_cashdeposit",
    "finance.add_cashdeposit",
    "finance.view_staffaccount",
    "finance.view_staffledgerentry",
]

# Sees and assigns everyone's work; the view_all_* grants lift row-scoping.
MANAGER_PERMS = [
    # Invoices — full lifecycle + cross-rep visibility + reassignment
    "sales.view_invoice", "sales.add_invoice", "sales.change_invoice",
    "sales.delete_invoice", "sales.issue_invoice", "sales.cancel_invoice",
    "sales.view_sales_report", "sales.view_financial_report",
    "sales.view_all_invoice", "sales.assign_salesperson",
    # Customers (all reps' books)
    "sales.view_customer", "sales.add_customer", "sales.change_customer",
    "sales.delete_customer", "sales.view_all_customer",
    # Payments (all)
    "sales.view_payment", "sales.add_payment", "sales.change_payment",
    "sales.view_all_payment",
    # Deliveries — dispatch board
    "sales.view_delivery", "sales.add_delivery", "sales.change_delivery",
    "sales.delete_delivery", "sales.view_all_delivery", "sales.assign_delivery",
    # Catalog + pricing
    "catalog.view_product", "catalog.add_product", "catalog.change_product",
    "catalog.view_service", "catalog.add_service", "catalog.change_service",
    "catalog.view_category", "catalog.add_category", "catalog.change_category",
    "catalog.view_supplier", "catalog.add_supplier", "catalog.change_supplier",
    # Optional automotive extension — shared lookup and fitment management
    "automotive.view_vehiclemake", "automotive.add_vehiclemake", "automotive.change_vehiclemake",
    "automotive.view_vehiclemodel", "automotive.add_vehiclemodel", "automotive.change_vehiclemodel",
    "automotive.view_vehiclegeneration", "automotive.add_vehiclegeneration", "automotive.change_vehiclegeneration",
    "automotive.view_vehicleengine", "automotive.add_vehicleengine", "automotive.change_vehicleengine",
    "automotive.view_vehicletrim", "automotive.add_vehicletrim", "automotive.change_vehicletrim",
    "automotive.view_productfitment", "automotive.add_productfitment", "automotive.change_productfitment",
    "automotive.delete_productfitment",
    # Inventory: purchase invoices, stock movements, physical counts + valuation
    "catalog.view_purchaseinvoice", "catalog.add_purchaseinvoice",
    "catalog.change_purchaseinvoice",
    "catalog.view_stockmovement", "catalog.add_stockmovement",
    "catalog.view_stocktake", "catalog.add_stocktake", "catalog.change_stocktake",
    "catalog.apply_stocktake", "catalog.view_inventory_valuation",
    # (Opening stock is a one-time bulk action reusing add_product/change_product
    #  + add_stockmovement above — it posts Stock In movements, no own permission.)
    # Finance — rate + cash reconciliation
    "finance.view_exchangerate", "finance.add_exchangerate", "finance.change_exchangerate",
    "finance.view_cashdeposit", "finance.add_cashdeposit", "finance.change_cashdeposit",
    "finance.confirm_cashdeposit", "finance.view_all_cashdeposit",
    "finance.view_expensecategory", "finance.add_expensecategory",
    "finance.change_expensecategory", "finance.delete_expensecategory",
    "finance.view_expense", "finance.add_expense", "finance.change_expense",
    "finance.delete_expense", "finance.post_expense", "finance.view_all_expense",
    "finance.view_staffaccount", "finance.add_staffaccount",
    "finance.change_staffaccount", "finance.delete_staffaccount",
    "finance.view_all_staffaccount",
    "finance.view_staffledgerentry", "finance.add_staffledgerentry",
    "finance.change_staffledgerentry", "finance.delete_staffledgerentry",
    "finance.resolve_staffledgerentry", "finance.view_all_staffledgerentry",
]

GROUPS = {
    "Sales Manager": MANAGER_PERMS,
    "Sales Representative": REP_PERMS,
    "Delivery Courier": COURIER_PERMS,
}


class Command(BaseCommand):
    help = "Create/refresh the Switch POS permission groups (Manager / Rep / Courier)."

    def handle(self, *args, **options):
        for group_name, perm_codes in GROUPS.items():
            group, _ = Group.objects.get_or_create(name=group_name)
            perms = []
            for code in perm_codes:
                app_label, codename = code.split(".", 1)
                try:
                    perms.append(
                        Permission.objects.get(
                            content_type__app_label=app_label, codename=codename
                        )
                    )
                except Permission.DoesNotExist:
                    self.stderr.write(self.style.WARNING(f"  missing permission: {code}"))
            group.permissions.set(perms)
            self.stdout.write(self.style.SUCCESS(f"{group_name}: {len(perms)} permissions set"))
        self.stdout.write(
            "Done. Assign each user to one group; keep the owner as a superuser. "
            "Reps/couriers see only their own rows — managers hold the view_all_* perms."
        )
