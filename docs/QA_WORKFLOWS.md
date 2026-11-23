# Sales CRM — Operational QA Workflows

Manual acceptance workflows with the results the code produces. Run them on a stack
that holds disposable data, never on live stock, invoices or payments. Paths are
relative to `/staff/`. Settings changes need a superuser; the other steps work for a
Sales Manager. The automated suites that cover the same rules are listed in
section 8.

## 1. Customer day: purchase, sale, cancellation to credit, credit reuse, report

Setup:

1. System Settings → CRM options → **Default currency**: choose **Both (USD / EUR)**.
2. `finance/rates/` (Exchange Rates): add a USD rate of 7 and a EUR rate of 8 (LYD per
   unit).

Steps:

1. `catalog/purchase-invoices/new/`: supplier name `QA Supplier`, invoice currency
   **EUR** (choose it first: changing the invoice currency later converts the entered
   amounts). One row: name `Day EUR pump`, product currency EUR, cost 20, selling price
   30, quantity 6. **Post Purchase Invoice** and confirm.
   Expect: invoice total 960 LYD (6 × 20 × 8); pump stock 6.
2. Same page, invoice currency **USD**: row `Day USD filter`, product currency USD,
   cost 10, selling price 15, quantity 3. Expect: filter stock 3.
3. `sales/new/`: customer `Day buyer`, discount 10 %, two pumps. **Save Draft**, then
   **Issue** on the invoice. Expect: total 432 LYD (2 × 30 EUR × 8 = 480, less 10 %);
   pump stock 4.
4. **Record Payment** of 100 LYD. Expect: status Partially Paid.
5. **Cancel** → payment action **Keep as customer credit** → **Confirm cancellation /
   settlement**. Expect: invoice cancelled; pump stock back to 6; the Customers list
   (`sales/customers/`) shows **Customer Credit (LYD)** 100.00 for `Day buyer`, and a
   later issued invoice for that customer shows **Available customer credit**.
6. Second invoice for `Day buyer`: one pump and one filter, **Issue**. Expect: total
   345 LYD (240 + 105).
7. **Apply customer credit**: choose the 100 LYD credit, amount 100. Expect: balance due
   245 LYD. Then **Record Payment** of 245.
   Expect: status Paid, balance due 0, Customer Credit (LYD) 0.00; stock 5 pumps and
   2 filters.
8. Exchange Rates: add a EUR rate of 10.
9. `sales/financial/` (Financial Report, current fiscal year).
   Expect: Revenue 345, Cost of Goods 230 (costs frozen at sale: 20 EUR × 8 plus
   10 USD × 7), Cash Collected 345 (the 100 LYD receipt converted to credit plus the
   245 LYD payment). The cancelled 432 LYD sale is not revenue, and the rate change
   alters none of these figures.

## 2. Stock integrity

- **Last unit**: two invoices each hold the only unit of a product. Issued at the
  same time, exactly one is issued and the other is rejected for insufficient stock;
  the balance is 0 and one outgoing movement exists. Issuing locks the invoice, the
  product and variant rows and checks the locked balances. This needs a database
  with row locks (PostgreSQL), so it is automated only (`LastItemConcurrencyTests`).
- **Shared limit**: a product has one unit on a blue variant. An invoice that holds a
  line for that variant and a line for the product without a variant is rejected on
  issue; the balance stays 1 and no outgoing movement is written.
- **Cancellation**: cancelling an issued invoice restores its stock once; resolving
  its payments later does not restore stock again.

## 3. Currency previews on intake pages

With both currencies active:

1. `catalog/stock-movements/opening-stock/` (Opening Stock; it redirects to a
   read-only record once opening stock has been finalized): set a row's product
   currency to EUR, enter a cost and selling price. Expect: the Manual LYD field shows
   the selling price converted at the EUR rate as an `≈` placeholder. Change the row
   to USD. Expect: the preview follows the USD rate.
2. `catalog/purchase-invoices/new/`: a row's previews and the totals use the rate of
   the invoice currency, whatever the row's product currency. Changing the invoice
   currency updates the rate badge and the totals, converts the entered cost and
   price amounts between the two rates, and changes the rate behind each row's LYD
   preview.

## 4. Optional enhancements

Use System Settings → **Optional enhancements** as a superuser.

1. Both enhancements off: the sidebar has no Vehicles Hub, Browse by Vehicle,
   Machines Hub or Browse machinery entry; `automotive/` and `machinery/` answer 404;
   the Product modal has no Fits vehicles, Part brand, OEM numbers or Compatible
   machines field; the Products ribbon has no browse or assign buttons and no Vehicle
   or Vehicle year filter; the group and user permission editors list no automotive
   or machinery permission.
2. Tick **Automotive compatibility** without saving. Expect: the Vehicle criteria
   block unlocks; **Manage vehicle data** stays disabled with a hint to save first.
   Save. Expect: the button opens the Vehicles Hub. Repeat for **Machinery
   compatibility** and **Manage machinery**.
3. Vehicle year, engine and transmission have no switches. Five switches exist:
   Machine type, Chassis / generation, Fuel type, Trim, Part position.
4. Give a fitment a trim, then switch **Trim** off and save. Expect: rejected with the
   number of fitments using it. Remove the trim from them and save again. Expect:
   accepted; the Vehicle Trims hub card is gone and `automotive/trims/` answers 404.
5. Products ribbon for each combination: neither on (no vehicle or machine buttons);
   vehicles only (Browse by vehicle, Assign vehicles); machinery only (Browse
   machinery, Assign machines); both (Assign vehicles and Assign machines only).
6. With a saved sidebar layout that contains Browse by Vehicle, switch automotive off.
   Expect: the entry disappears and a group left empty disappears. Switch it on.
   Expect: the entry returns at its saved position. The machinery switch behaves
   independently.
7. Switch an enhancement off and on again. Expect: makes, models, machines and
   fitments are unchanged.

## 5. Vehicle compatibility

Automotive on, a user with the vehicle permissions (Sales Manager).

1. Vehicles Hub (`automotive/`): add make `Toyota`, model `Corolla`; with Chassis /
   generation on, generation `E170` (2014–2019); add an engine and a trim.
2. Products: open a product modal; in **Fits vehicles** type `corolla 2017`, choose the
   suggestion, save. Expect: the tag is saved; the product card lists the label under
   **Fits vehicles**.
3. `automotive/browse/`: Toyota → Corolla → 2017. Expect: counts per step, the
   product listed once, a stock badge, the card opening from the result. Select an
   engine or generation. Expect: products with a blank engine or generation stay
   listed.
4. Sell the product on an invoice. Reach it again through a second compatible vehicle.
   Expect: the same reduced stock balance.
5. **Find a vehicle** with a vehicle that no product fits. Expect: the browser reaches
   it with no products listed and offers **Add part for this vehicle**, which opens
   the Product modal with the vehicle tagged.
6. **Search products** with a SKU, a barcode and an OEM number. Expect: matches
   without choosing a vehicle.
7. Products ribbon → **Assign vehicles**: two products, one vehicle. Expect: both gain
   the vehicle and existing compatibility remains. In a product modal, **Same cars
   as…** copies another product's tags.
8. Product card → **Manage compatibility**: enter the same row twice (duplicate error);
   enter two overlapping year ranges for one vehicle (rejected until **I reviewed and
   confirm intentional overlapping ranges** is ticked).
9. `catalog/purchase-invoices/new/`: open a row's **Fits vehicles**, add a vehicle,
   post. Expect: the created product carries the fitment and holds one stock balance.
10. Products list: **Vehicle** and **Vehicle year** filters, and a keyword search for a
    make, a chassis code and an OEM number, each return the product once.
11. Till (when POS is on): **By vehicle** lists the products that fit the chosen
    vehicle.

## 6. Machinery compatibility

Machinery on; a user with the machinery permissions (Sales Manager).

1. Run `python manage.py seed_machine_categories`; run it a second time. Expect: no
   second set of records.
2. `machinery/browse/`: Concrete pump & mixer → CIFA → F8 → Hydraulic → Pump → Piston.
   Expect: breadcrumbs at each step and branches offered although no part exists.
   Choose F9. Expect: no category branches.
3. At Piston, **Add part**. Expect: the Product modal opens with category Hydraulic /
   Pump / Piston and machine CIFA / F8 preselected. Save; the product appears in the
   browser path and on its card under **Compatible machines**.
4. Open the Hydraulic / Repair branch. Expect: only **Add service** is offered; the
   Repair service shows **Per job**, a service badge and no stock badge; the Product
   modal's category list excludes Repair. A user without `catalog.view_service` sees
   no services in the browser.
5. Machine models list: add a machine with only a machine type. Expect: it appears
   directly under its type in the browser, **Find a machine** finds it by the type
   name, and the Product modal offers it. Adding the same type, manufacturer and name
   again is rejected.
6. Products ribbon → **Assign machines**. Expect: links are added and existing links
   stay.
7. A purchase-invoice row: open **Compatible machines** (a separate row under the
   item fields), choose a machine, post. Expect: one product, one stock balance, the
   machine link on the product.
8. Opening-stock workbook with a category cell `Hydraulic/Pump/Piston`. Expect: the row
   resolves to that category. With a second `Piston` under another parent, the bare
   name `Piston` is rejected as ambiguous.
9. Switch machinery off. Expect: `machinery/browse/` answers 404 and the Product modal
   has no machine field. Switch it on. Expect: the stored links are intact.

## 7. Purchase-invoice editor layout

At `catalog/purchase-invoices/new/` check both modes: one active currency (the Product
currency column is hidden) and both currencies. Scroll fully right: the item table and
the footer end at the same edge, the Foreign total and Total (LYD) footer cells sit
under their line-total columns, and no empty column follows the remove column. Repeat
after **Add Item**.

## 8. Automated suites

From a source checkout (the Docker image excludes `tests/`, `docs/` and the compose
files):

```bash
python manage.py test finance catalog sales common public_catalog automotive machinery tests \
    --settings=config.settings_dev_sqlite
node --test tests/js/invoice_editor.test.cjs
```

| Area | Module |
|---|---|
| Customer day, shared stock limit, last-unit race (PostgreSQL) | `sales/tests/test_operation_workflows.py` |
| Invoice lifecycle, pricing, stock deduction and restore, receipts | `sales/tests/test_sales.py`, `test_invoice_regressions.py`, `test_business_math.py` |
| Cancellation, refunds, customer credit, concurrent receipt resolution | `sales/tests/test_payment_resolution.py`, `test_credit_concurrency.py` |
| Financial report and workbook exports | `sales/tests/test_financial.py`, `test_report_export_safety.py` |
| Ownership and permission isolation | `sales/tests/test_visibility.py` |
| Till | `sales/tests/test_pos.py` |
| Purchase invoices, opening stock, stock counts, currencies | `catalog/tests/test_purchase_invoices.py`, `test_opening_stock.py`, `test_stocktake.py`, `test_product_currencies.py` |
| Exchange rates, pricing currency | `finance/tests/` |
| Vehicle compatibility | `automotive/tests/` |
| Machinery compatibility | `machinery/tests/test_workflows.py` |
| Enhancement sidebar visibility | `common/tests/test_enhancement_sidebar.py` |
| Invoice editor row removal | `tests/js/invoice_editor.test.cjs` |
