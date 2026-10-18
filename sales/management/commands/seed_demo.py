"""
Seed realistic demo data for local testing / screenshots / demos.

Creates exchange rates, demo staff, suppliers, catalog (categories, products
with barcodes/variants + stock, services), customers, purchase invoices,
stock takes, expenses, staff ledger entries, deliveries, and a spread of
invoices across every status (draft / issued / partial / paid / cancelled)
with payments and cash deposits.

    python manage.py seed_demo            # idempotent top-up
    python manage.py seed_demo --reset    # wipe demo tables first (DESTRUCTIVE)

Reference data (rates / staff / catalog / customers) is idempotent via
get_or_create. Operational demo documents are only created when no invoices
exist yet (or after --reset) so re-running never piles up duplicate invoices.
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from catalog.models import (
    Category, Product, ProductVariant, PurchaseInvoice, PurchaseInvoiceLine, Service,
    StockMovement, StockTake, StockTakeLine, Supplier,
)
from finance.models import (
    CashDeposit, ExchangeRate, Expense, ExpenseCategory, StaffAccount,
    StaffLedgerEntry,
)
from sales.models import Customer, Delivery, Invoice, InvoiceItem, Payment
from sales.services import cancel_invoice, issue_invoice

D = lambda v: Decimal(str(v))  # noqa: E731 — terse Decimal helper for readability


class Command(BaseCommand):
    help = "Seed demo data (rates, catalog, customers, invoices, payments) for testing."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete existing demo data before seeding (DESTRUCTIVE).",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        self.actor = get_user_model().objects.filter(is_superuser=True).first()

        if options["reset"]:
            self._reset()

        users = self._seed_users()
        if self.actor is None:
            self.actor = users["manager"]
        self._seed_rates()
        suppliers = self._seed_suppliers()
        cats = self._seed_categories()
        products = self._seed_products(cats)
        services = self._seed_services()
        customers = self._seed_customers()

        if Invoice.objects.exists():
            self.stdout.write(self.style.WARNING(
                "Invoices already exist — skipping operational demo documents. Re-run with --reset to rebuild."
            ))
        else:
            self._seed_purchase_invoices(products, suppliers)
            deposits = self._seed_deposits()
            invoices = self._seed_invoices(products, services, customers, users, deposits)
            self._seed_deliveries(invoices, users)
            self._seed_expenses(users)
            self._seed_staff_ledger(users)
            self._seed_stock_takes(products)

        self.stdout.write(self.style.SUCCESS("Demo data ready."))
        self._summary()

    # ---------------------------------------------------------------- reset ---
    def _reset(self):
        # Order matters: clear the stock ledger before products (PROTECT), and
        # invoices (which SET_NULL/CASCADE their children) before customers/rates.
        StaffLedgerEntry.all_objects.all().hard_delete()
        StaffAccount.all_objects.all().hard_delete()
        Expense.all_objects.all().hard_delete()
        ExpenseCategory.all_objects.all().hard_delete()
        Delivery.all_objects.all().hard_delete()
        Payment.all_objects.all().hard_delete()
        InvoiceItem.objects.all().delete()
        Invoice.all_objects.all().hard_delete()
        StockTakeLine.objects.all().delete()
        StockTake.all_objects.all().hard_delete()
        StockMovement.all_objects.all().hard_delete()
        PurchaseInvoiceLine.objects.all().delete()
        PurchaseInvoice.all_objects.all().hard_delete()
        Product.all_objects.all().hard_delete()
        Service.all_objects.all().hard_delete()
        Category.all_objects.all().hard_delete()
        Supplier.all_objects.all().hard_delete()
        Customer.all_objects.all().hard_delete()
        CashDeposit.all_objects.all().hard_delete()
        ExchangeRate.all_objects.all().hard_delete()
        self.stdout.write(self.style.WARNING("Reset: demo tables cleared."))

    # ------------------------------------------------------------- reference ---
    def _seed_users(self):
        User = get_user_model()
        specs = [
            ("demo_manager", "Mariam", "Operations Manager", True),
            ("demo_rep_nadia", "Nadia", "Sales Representative", False),
            ("demo_rep_yousef", "Yousef", "Sales Representative", False),
            ("demo_courier_ali", "Ali", "Delivery Courier", False),
            ("demo_tech_mona", "Mona", "Field Technician", False),
        ]
        users = {}
        for username, first_name, last_name, is_staff in specs:
            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    "first_name": first_name,
                    "last_name": last_name,
                    "email": f"{username}@switch.local",
                    "is_staff": is_staff,
                },
            )
            if created:
                user.set_password("demo12345")
                user.save(update_fields=["password"])
            users[username.replace("demo_", "")] = user
        return users

    def _seed_rates(self):
        # Append-only history; the newest row is the live rate. Create official
        # rates first, then the higher parallel/custom rates so fresh seeds have
        # a realistic spread and the last row wins.
        ExchangeRate.objects.get_or_create(
            rate=D("6.41"), source=ExchangeRate.SOURCE_OFFICIAL,
            defaults={"note": "Seed: CBL official"},
        )
        ExchangeRate.objects.get_or_create(
            rate=D("6.43"), source=ExchangeRate.SOURCE_OFFICIAL,
            defaults={"note": "Seed: CBL official updated"},
        )
        ExchangeRate.objects.get_or_create(
            rate=D("8.35"), source=ExchangeRate.SOURCE_BLACK_MARKET,
            defaults={"note": "Seed: parallel-market previous"},
        )
        rate, _ = ExchangeRate.objects.get_or_create(
            rate=D("8.50"), source=ExchangeRate.SOURCE_BLACK_MARKET,
            defaults={"note": "Seed: parallel-market"},
        )
        rate, _ = ExchangeRate.objects.get_or_create(
            rate=D("8.65"), source=ExchangeRate.SOURCE_CUSTOM,
            defaults={"note": "Seed: shop working rate"},
        )
        return rate

    def _seed_suppliers(self):
        specs = [
            ("Tripoli Secure Imports", "0912001001", "Tripoli Free Zone", "Primary smart-lock importer"),
            ("Misrata Metal Works", "0923002002", "Misrata Industrial Road", "Plates, strikes and brackets"),
            ("Benghazi Access Tech", "0944003003", "Benghazi, Dubai St", "Controllers and electronics"),
            ("Zawiya Logistics Hub", "0915004004", "Zawiya, Port Road", "Emergency replenishment"),
        ]
        return {
            name: Supplier.objects.get_or_create(
                name=name,
                defaults={"phone": phone, "address": address, "notes": notes},
            )[0]
            for name, phone, address, notes in specs
        }

    def _seed_categories(self):
        names = [
            "Smart Locks", "Controllers", "Sensors", "Power", "Spare Parts",
            "Access Cards", "Door Hardware", "Accessories",
        ]
        return {
            n: Category.objects.get_or_create(name=n, defaults={"is_active": True})[0]
            for n in names
        }

    def _seed_products(self, cats):
        # (name, category, barcode, cost_usd, markup%, unit, reorder,
        #  initial_stock, lyd_override, track_stock, color, size)
        specs = [
            ("Switch Pro Deadbolt", "Smart Locks", "6291041500213", 85, 30, "piece", 6, 42, None, True, Product.COLOR_BLACK, "ANSI / 70 mm"),
            ("Switch Pro Deadbolt - Brass", "Smart Locks", "6291041500214", 88, 32, "piece", 4, 18, None, True, Product.COLOR_GOLD, "ANSI / 70 mm"),
            ("Switch Lite Keypad", "Smart Locks", "6291041500220", 45, 35, "piece", 8, 6, None, True, Product.COLOR_WHITE, "Slim / 160x68 mm"),
            ("Switch Glass Door Lock", "Smart Locks", "6291041500221", 115, 28, "piece", 3, 12, None, True, Product.COLOR_GRAY, "Glass 10-12 mm"),
            ("Switch Hotel Lock", "Smart Locks", "6291041500222", 92, 34, "piece", 5, 16, None, True, Product.COLOR_GOLD, "RFID / 60 mm"),
            ("Outdoor Gate Controller", "Controllers", "6291041500223", 64, 42, "piece", 5, 10, None, True, Product.COLOR_NAVY, "Weatherproof IP65"),
            ("Wi-Fi Bridge", "Controllers", "6291041500224", 22, 50, "piece", 10, 35, None, True, Product.COLOR_WHITE, "2.4 GHz"),
            ("Bluetooth Gateway", "Controllers", "6291041500225", 28, 48, "piece", 8, 30, None, True, Product.COLOR_BLACK, "BLE / USB-C"),
            ("Fingerprint Module", "Spare Parts", "6291041500237", 18, 40, "piece", 10, 70, None, True, Product.COLOR_BLACK, "FPC1020"),
            ("Relay Board 2CH", "Controllers", "6291041500238", 7.5, 55, "piece", 15, 90, None, True, Product.COLOR_GREEN, "12V / 2 channel"),
            ("Battery Pack CR123", "Power", "6291041500239", 12, 45, "set", 12, 48, None, True, Product.COLOR_BLUE, "4-pack"),
            ("Backup Power Supply", "Power", "6291041500240", 38, 35, "piece", 6, 12, None, True, Product.COLOR_BLACK, "12V 5A"),
            ("Door Sensor Pair", "Sensors", "6291041500241", 9, 52, "pair", 15, 65, None, True, Product.COLOR_WHITE, "Magnetic / 25 mm"),
            ("Magnetic Contact Heavy", "Sensors", "6291041500242", 14, 48, "pair", 10, 30, None, True, Product.COLOR_GRAY, "Metal door"),
            ("Spare Key Fob", "Access Cards", "6291041500244", 4, 50, "piece", 25, 18, None, True, Product.COLOR_BLACK, "13.56 MHz"),
            ("RFID Card Pack", "Access Cards", "6291041500245", 11, 65, "box", 8, 24, None, True, Product.COLOR_WHITE, "Box of 20"),
            ("NFC Sticker Roll", "Access Cards", "6291041500246", 16, 58, "box", 6, 14, None, True, Product.COLOR_TEAL, "Roll of 50"),
            ("Mounting Plate", "Door Hardware", "6291041500251", 6, 25, "piece", 15, 90, None, True, Product.COLOR_GRAY, "Universal"),
            ("Strike Plate Heavy Duty", "Door Hardware", "6291041500252", 13, 45, "piece", 10, 40, None, True, Product.COLOR_GRAY, "Stainless"),
            ("Emergency Override Cylinder", "Door Hardware", "6291041500253", 21, 38, "piece", 8, 22, None, True, Product.COLOR_GOLD, "Euro profile"),
            ("Cable Trunking 20mm", "Accessories", "6291041500254", 2.4, 70, "meter", 50, 120, None, True, Product.COLOR_WHITE, "20 mm"),
            ("Install Screw Kit", "Accessories", "6291041500255", 3.75, 80, "set", 30, 75, None, True, Product.COLOR_GRAY, "Mixed fasteners"),
            ("Gift Card (unrelated goods)", "Accessories", "6291041500268", 0, 0, "piece", 0, 0, D("250.00"), False, Product.COLOR_PURPLE, "LYD 250"),
            ("Consultation Voucher", "Accessories", "6291041500269", 0, 0, "piece", 0, 0, D("150.00"), False, Product.COLOR_TEAL, "One visit"),
        ]
        out = {}
        for name, cat, barcode, cost, markup, unit, reorder, stock, override, track, color, size in specs:
            p, created = Product.objects.get_or_create(
                name=name,
                defaults={
                    "category": cats[cat],
                    "barcode": barcode,
                    "cost_usd": D(cost),
                    "markup_percent": D(markup),
                    "unit": unit,
                    "reorder_level": D(reorder),
                    "price_lyd_override": override,
                    "track_stock": track,
                    "color": color,
                    "size": size,
                },
            )
            variant = ProductVariant.get_or_create_for(p, color, size)
            # Seed opening stock exactly once (idempotent: only if no ledger rows).
            if created and track and stock and not p.movements.exists():
                StockMovement.objects.create(
                    product=p, variant=variant, movement_type=StockMovement.TYPE_IN,
                    quantity=D(stock), reason="Seed: opening stock",
                )
            out[name] = p
        return out

    def _seed_services(self):
        specs = [
            ("Standard Installation", Service.TYPE_INSTALLATION, 20),
            ("Premium Door Retrofit", Service.TYPE_INSTALLATION, 45),
            ("Glass Door Installation", Service.TYPE_INSTALLATION, 60),
            ("Annual Maintenance", Service.TYPE_MAINTENANCE, 35),
            ("Emergency Call-out", Service.TYPE_MAINTENANCE, 30),
            ("Extended Warranty", Service.TYPE_WARRANTY, 15),
            ("Enterprise Warranty", Service.TYPE_WARRANTY, 95),
            ("City Delivery", Service.TYPE_DELIVERY, 10),
            ("Intercity Delivery", Service.TYPE_DELIVERY, 32),
            ("Custom Job (quote)", Service.TYPE_OTHER, None),
            ("Access Audit", Service.TYPE_OTHER, 75),
        ]
        return {
            name: Service.objects.get_or_create(
                name=name,
                defaults={"service_type": stype, "price_usd": (D(price) if price is not None else None)},
            )[0]
            for name, stype, price in specs
        }

    def _seed_customers(self):
        specs = [
            ("Ahmed Al-Mansouri", "0913001122", "Tripoli, Gargaresh Rd"),
            ("Sara Trading Co.", "0925004433", "Benghazi, Dubai St"),
            ("Khalid Enterprises", "0918887766", "Misrata, Tripoli St"),
            ("Fatima Interiors", "0947001199", "Zawiya, Central Market"),
            ("Tajoura Clinic", "0914408801", "Tripoli, Tajoura"),
            ("Libya Co-working Hub", "0922205502", "Tripoli, Ben Ashour"),
            ("Misrata Cold Stores", "0917789912", "Misrata, Free Zone"),
            ("Benghazi Hotel Group", "0944432100", "Benghazi, Corniche"),
            ("Zliten School Supplies", "0916657788", "Zliten, School St"),
            ("Derna Boutique", "0925541100", "Derna, Old Souq"),
            ("Sabratha Villas", "0919027722", "Sabratha, Coastal Road"),
            ("Gharyan Workshop", "0941183300", "Gharyan, Industrial Area"),
        ]
        return [
            Customer.objects.get_or_create(
                name=name, defaults={"phone": phone, "address": addr},
            )[0]
            for name, phone, addr in specs
        ]

    # ---------------------------------------------------------- procurement ---
    def _purchase_invoice(self, supplier, days_ago, lines):
        invoice = PurchaseInvoice.objects.create(
            supplier=supplier,
            supplier_name=supplier.name,
            supplier_phone=supplier.phone,
            supplier_address=supplier.address,
            invoice_date=timezone.localdate() - timedelta(days=days_ago),
            exchange_rate=D("8.35"),
            notes="Seed: inbound stock",
        )
        for product, qty in lines:
            variant = ProductVariant.get_or_create_for(product, product.color, product.size)
            PurchaseInvoiceLine.objects.create(
                invoice=invoice,
                product=product,
                variant=variant,
                category=product.category,
                description=product.name,
                unit=product.unit,
                barcode=product.barcode,
                color=variant.color or None,
                size=variant.size or None,
                cost_usd=product.cost_usd,
                markup_percent=product.markup_percent,
                price_usd=product.price_usd,
                price_lyd_override=product.price_lyd_override,
                quantity=D(qty),
            )
            StockMovement.objects.create(
                product=product,
                variant=variant,
                movement_type=StockMovement.TYPE_IN,
                quantity=D(qty),
                reason=f"Seed purchase invoice {invoice.number}",
                reference=invoice.number,
                purchase_invoice=invoice,
            )
        invoice.recalc_totals()
        return invoice

    def _seed_purchase_invoices(self, products, suppliers):
        P, S = products, suppliers
        return [
            self._purchase_invoice(
                S["Tripoli Secure Imports"], 24,
                [
                    (P["Switch Pro Deadbolt"], 12),
                    (P["Switch Glass Door Lock"], 6),
                    (P["Switch Hotel Lock"], 8),
                    (P["Wi-Fi Bridge"], 20),
                ],
            ),
            self._purchase_invoice(
                S["Benghazi Access Tech"], 15,
                [
                    (P["Outdoor Gate Controller"], 8),
                    (P["Bluetooth Gateway"], 16),
                    (P["Relay Board 2CH"], 35),
                    (P["Door Sensor Pair"], 30),
                ],
            ),
            self._purchase_invoice(
                S["Misrata Metal Works"], 9,
                [
                    (P["Mounting Plate"], 40),
                    (P["Strike Plate Heavy Duty"], 20),
                    (P["Emergency Override Cylinder"], 12),
                    (P["Install Screw Kit"], 30),
                ],
            ),
            self._purchase_invoice(
                S["Zawiya Logistics Hub"], 3,
                [
                    (P["Spare Key Fob"], 25),
                    (P["RFID Card Pack"], 10),
                    (P["NFC Sticker Roll"], 8),
                    (P["Battery Pack CR123"], 18),
                ],
            ),
        ]

    def _seed_deposits(self):
        deposits = {}
        specs = [
            ("DEP-SHIFT-001", CashDeposit.METHOD_CASH, D("0.00"), False, "Seed: linked counter-cash batch"),
            ("DEP-SHIFT-002", CashDeposit.METHOD_BANK, D("0.00"), True, "Seed: linked bank-transfer batch"),
            ("DEP-MANUAL-001", CashDeposit.METHOD_CHEQUE, D("875.00"), False, "Seed: standalone cheque in review"),
        ]
        for ref, method, amount, confirm, notes in specs:
            dep = CashDeposit.objects.create(
                reference=ref,
                method=method,
                amount=amount,
                deposited_at=timezone.localdate(),
                notes=notes,
            )
            if confirm:
                dep.confirm(self.actor)
            deposits[ref] = dep
        return deposits

    # ------------------------------------------------------------- invoices ---
    def _add_line(self, inv, spec):
        kind = spec[0]
        if kind == "product":
            p, qty = spec[1], D(spec[2])
            variant = ProductVariant.get_or_create_for(p, p.color, p.size)
            InvoiceItem.objects.create(
                invoice=inv, kind=InvoiceItem.KIND_PRODUCT, product=p, description=p.name,
                unit_price_lyd=p.selling_price_lyd(inv.exchange_rate) or D(0),
                unit_price_usd=p.effective_price_usd, unit_cost_usd=p.cost_usd,
                variant=variant, color=variant.color or None, size=variant.size or None, quantity=qty,
            )
        elif kind == "service":
            s, qty = spec[1], D(spec[2])
            InvoiceItem.objects.create(
                invoice=inv, kind=InvoiceItem.KIND_SERVICE, service=s, description=s.name,
                unit_price_lyd=s.selling_price_lyd(inv.exchange_rate) or D(0),
                unit_price_usd=s.price_usd, quantity=qty,
            )
        else:  # ("custom", description, unit_price_lyd, qty)
            InvoiceItem.objects.create(
                invoice=inv, kind=InvoiceItem.KIND_CUSTOM, description=spec[1],
                unit_price_lyd=D(spec[2]), quantity=D(spec[3]),
            )

    def _invoice(self, *, customer=None, name="", lines, status="draft",
                 discount_percent=0, days_ago=0, pay_fraction=None,
                 salesperson=None, created_by=None, deposit=None,
                 payment_method=Payment.METHOD_CASH):
        inv = Invoice(
            customer=customer,
            customer_name=name or (customer.name if customer else ""),
            discount_percent=D(discount_percent),
            invoice_date=timezone.localdate() - timedelta(days=days_ago),
            salesperson=salesperson,
            created_by=created_by or salesperson,
        )
        if customer:
            inv.customer_phone = customer.phone
            inv.customer_address = customer.address
        inv.save()  # assigns number + freezes the current exchange rate

        for spec in lines:
            self._add_line(inv, spec)
        inv.recalc_totals()

        if status in ("issued", "partial", "paid", "cancelled"):
            issue_invoice(inv, self.actor)
            inv.refresh_from_db()
            if status in ("partial", "paid"):
                frac = D(1) if status == "paid" else (pay_fraction or D("0.5"))
                amount = (inv.total_lyd * frac).quantize(D("0.01"))
                if amount > 0:
                    Payment.objects.create(
                        invoice=inv,
                        amount=amount,
                        method=payment_method,
                        deposit=deposit,
                        created_by=created_by or salesperson,
                        paid_at=timezone.now() - timedelta(days=max(days_ago - 1, 0)),
                    )
            if status == "cancelled":
                cancel_invoice(inv, self.actor)
        return inv

    def _seed_invoices(self, products, services, customers, users, deposits):
        P, S = products, services
        rep1, rep2 = users["rep_nadia"], users["rep_yousef"]
        cash_batch = deposits["DEP-SHIFT-001"]
        bank_batch = deposits["DEP-SHIFT-002"]
        invoices = []
        cases = [
            (customers[0], "paid", 45, 0, rep1, cash_batch, Payment.METHOD_CASH,
             [("product", P["Switch Pro Deadbolt"], 1), ("service", S["Standard Installation"], 1)]),
            (customers[1], "partial", 41, 0, rep2, cash_batch, Payment.METHOD_CASH,
             [("product", P["Switch Lite Keypad"], 2), ("product", P["Spare Key Fob"], 3)]),
            (customers[2], "issued", 38, 10, rep1, None, Payment.METHOD_CASH,
             [("product", P["Fingerprint Module"], 2), ("service", S["Annual Maintenance"], 1)]),
            (customers[3], "cancelled", 34, 0, rep2, None, Payment.METHOD_CASH,
             [("product", P["Mounting Plate"], 4)]),
            (None, "draft", 30, 0, rep1, None, Payment.METHOD_CASH,
             [("custom", "On-site consultation", 150, 1), ("service", S["City Delivery"], 1)]),
            (customers[4], "paid", 26, 0, rep1, bank_batch, Payment.METHOD_BANK,
             [("product", P["Switch Glass Door Lock"], 2), ("service", S["Glass Door Installation"], 2)]),
            (customers[5], "partial", 23, 5, rep2, cash_batch, Payment.METHOD_CASH,
             [("product", P["Wi-Fi Bridge"], 4), ("product", P["Bluetooth Gateway"], 2), ("service", S["Access Audit"], 1)]),
            (customers[6], "issued", 20, 0, rep1, None, Payment.METHOD_CASH,
             [("product", P["Outdoor Gate Controller"], 1), ("product", P["Door Sensor Pair"], 3)]),
            (customers[7], "paid", 17, 12.5, rep2, bank_batch, Payment.METHOD_BANK,
             [("product", P["Switch Hotel Lock"], 6), ("product", P["RFID Card Pack"], 3), ("service", S["Enterprise Warranty"], 1)]),
            (customers[8], "partial", 14, 0, rep1, cash_batch, Payment.METHOD_CASH,
             [("product", P["Battery Pack CR123"], 4), ("product", P["NFC Sticker Roll"], 2)]),
            (customers[9], "issued", 11, 0, rep2, None, Payment.METHOD_CASH,
             [("product", P["Strike Plate Heavy Duty"], 5), ("product", P["Emergency Override Cylinder"], 2)]),
            (customers[10], "cancelled", 9, 0, rep1, None, Payment.METHOD_CASH,
             [("product", P["Backup Power Supply"], 2), ("service", S["Intercity Delivery"], 1)]),
            (customers[11], "paid", 7, 0, rep2, cash_batch, Payment.METHOD_CASH,
             [("product", P["Cable Trunking 20mm"], 18.5), ("product", P["Install Screw Kit"], 4)]),
            (customers[0], "paid", 5, 0, rep1, bank_batch, Payment.METHOD_BANK,
             [("product", P["Gift Card (unrelated goods)"], 2)]),
            (customers[2], "issued", 4, 7.5, rep2, None, Payment.METHOD_CASH,
             [("product", P["Switch Pro Deadbolt - Brass"], 1), ("service", S["Premium Door Retrofit"], 1)]),
            (customers[4], "partial", 3, 0, rep1, cash_batch, Payment.METHOD_CASH,
             [("product", P["Magnetic Contact Heavy"], 4), ("product", P["Relay Board 2CH"], 3)]),
            (customers[5], "paid", 2, 0, rep2, bank_batch, Payment.METHOD_BANK,
             [("product", P["Consultation Voucher"], 1), ("service", S["Emergency Call-out"], 1)]),
            (None, "draft", 0, 0, rep1, None, Payment.METHOD_CASH,
             [("custom", "Quoted enterprise access plan", 2150, 1), ("service", S["Custom Job (quote)"], 1)]),
        ]
        for customer, status, days, discount, rep, deposit, method, lines in cases:
            invoices.append(self._invoice(
                customer=customer,
                name="" if customer else "Walk-in — Omar",
                status=status,
                days_ago=days,
                discount_percent=discount,
                pay_fraction=D("0.42") if status == "partial" else None,
                salesperson=rep,
                created_by=rep,
                deposit=deposit,
                payment_method=method,
                lines=lines,
            ))
        return invoices

    # ------------------------------------------------------------ operations ---
    def _seed_deliveries(self, invoices, users):
        courier = users["courier_ali"]
        statuses = [
            Delivery.STATUS_DELIVERED, Delivery.STATUS_OUT, Delivery.STATUS_ASSIGNED,
            Delivery.STATUS_PENDING, Delivery.STATUS_FAILED, Delivery.STATUS_CANCELLED,
        ]
        for idx, inv in enumerate([i for i in invoices if i.status != Invoice.STATUS_DRAFT][:10]):
            Delivery.objects.create(
                invoice=inv,
                assigned_to=courier if idx % 4 != 3 else None,
                status=statuses[idx % len(statuses)],
                scheduled_date=inv.invoice_date + timedelta(days=1),
                notes="Seed delivery route",
                created_by=users["manager"],
            )

    def _seed_expenses(self, users):
        cats = {
            name: ExpenseCategory.objects.create(name=name)
            for name in ("Rent", "Fuel", "Install Materials", "Marketing", "Utilities")
        }
        specs = [
            ("Rent", D("1850.00"), 28, Expense.STATUS_POSTED, Expense.METHOD_BANK, "July showroom rent"),
            ("Fuel", D("240.75"), 18, Expense.STATUS_POSTED, Expense.METHOD_CASH, "Delivery fuel"),
            ("Install Materials", D("318.40"), 10, Expense.STATUS_POSTED, Expense.METHOD_CASH, "Anchors and wiring"),
            ("Marketing", D("725.00"), 6, Expense.STATUS_DRAFT, Expense.METHOD_BANK, "Draft campaign"),
            ("Utilities", D("430.20"), 2, Expense.STATUS_VOID, Expense.METHOD_BANK, "Voided duplicate bill"),
        ]
        for cat, amount, days, status, method, note in specs:
            expense = Expense.objects.create(
                category=cats[cat],
                amount_lyd=amount,
                expense_date=timezone.localdate() - timedelta(days=days),
                method=method,
                paid_by=users["manager"],
                status=status,
                notes=note,
                created_by=users["manager"],
            )
            if status == Expense.STATUS_VOID:
                expense.void(users["manager"])

    def _seed_staff_ledger(self, users):
        rows = [
            ("rep_nadia", StaffLedgerEntry.TYPE_SERVICE_EARNED, D("390.00"), False, "Commission on June invoices"),
            ("rep_nadia", StaffLedgerEntry.TYPE_ADVANCE, D("125.00"), True, "Phone allowance advance"),
            ("rep_yousef", StaffLedgerEntry.TYPE_SERVICE_EARNED, D("460.00"), False, "Commission on enterprise sales"),
            ("rep_yousef", StaffLedgerEntry.TYPE_PAY_STAFF, D("250.00"), False, "Partial payout"),
            ("courier_ali", StaffLedgerEntry.TYPE_CASH_CHECKOUT, D("180.00"), True, "Cash collected on route"),
            ("tech_mona", StaffLedgerEntry.TYPE_REIMBURSEMENT, D("95.50"), False, "Install materials reimbursement"),
            ("tech_mona", StaffLedgerEntry.TYPE_LOAN, D("300.00"), True, "Tool loan pending confirmation"),
        ]
        for user_key, entry_type, amount, requires_confirmation, note in rows:
            account = StaffAccount.for_user(users[user_key])
            StaffLedgerEntry.objects.create(
                account=account,
                entry_type=entry_type,
                amount_lyd=amount,
                requires_user_confirmation=requires_confirmation,
                reference="Seed ledger",
                notes=note,
                created_by=users["manager"],
            )

    def _seed_stock_takes(self, products):
        applied = StockTake.objects.create(
            count_date=timezone.localdate() - timedelta(days=1),
            notes="Seed: applied cycle count for demo variance math",
            created_by=self.actor,
        )
        for name, counted_delta in [
            ("Spare Key Fob", D("-2.00")),
            ("Relay Board 2CH", D("1.00")),
            ("Battery Pack CR123", D("0.00")),
        ]:
            product = products[name]
            product.refresh_from_db()
            StockTakeLine.objects.create(
                stock_take=applied,
                product=product,
                system_qty=product.stock_qty,
                counted_qty=product.stock_qty + counted_delta,
            )
        applied.apply(self.actor)

        open_take = StockTake.objects.create(
            count_date=timezone.localdate(),
            notes="Seed: open count sheet with partially counted lines",
            created_by=self.actor,
        )
        for name, counted_delta in [
            ("Switch Pro Deadbolt", None),
            ("Wi-Fi Bridge", D("0.00")),
            ("Mounting Plate", D("-1.00")),
        ]:
            product = products[name]
            product.refresh_from_db()
            counted = None if counted_delta is None else product.stock_qty + counted_delta
            StockTakeLine.objects.create(
                stock_take=open_take,
                product=product,
                system_qty=product.stock_qty,
                counted_qty=counted,
            )

    # -------------------------------------------------------------- summary ---
    def _summary(self):
        rows = [
            ("Demo users", get_user_model().objects.filter(username__startswith="demo_").count()),
            ("Exchange rates", ExchangeRate.objects.count()),
            ("Suppliers", Supplier.objects.count()),
            ("Categories", Category.objects.count()),
            ("Products", Product.objects.count()),
            ("Services", Service.objects.count()),
            ("Customers", Customer.objects.count()),
            ("Purchase invoices", PurchaseInvoice.objects.count()),
            ("Invoices", Invoice.objects.count()),
            ("Payments", Payment.objects.count()),
            ("Cash deposits", CashDeposit.objects.count()),
            ("Deliveries", Delivery.objects.count()),
            ("Expenses", Expense.objects.count()),
            ("Staff ledger", StaffLedgerEntry.objects.count()),
            ("Stock takes", StockTake.objects.count()),
        ]
        for label, count in rows:
            self.stdout.write(f"  {label:<16} {count}")
