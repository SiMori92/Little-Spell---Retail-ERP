# Slice G-1 report — raise a purchase order by file

PROMPT 11. SAMPLE mode. **This slice posts nothing.** A PO is a commitment, not a transaction. The
catalogue is unchanged: v1.6, 28 event types, no event emitted by any G-1 path.

**Branch and commits:** built on `claude/slice-g1-raise-po`, cut from `main` at `03cab60`, and
fast-forwarded onto `main`. Code commit `8fe00b4`. This report is the following commit on the same line.
(The session's tooling blocks edits in the primary checkout, so the work was done in the session worktree and
landed on `main` by fast-forward only. The history on `main` is identical to committing there directly.)

**CI (PostgreSQL 16 service, no SQLite):** run **`36314135646`** on `8fe00b4`: **231 tests, OK**
(<https://github.com/SiMori92/Little-Spell---Retail-ERP/actions/runs/36314135646>). Local runs on
PostgreSQL 16.2 gave the same result. Main was confirmed at `03cab60` before work started (CI run
`36313235355`, 201 tests OK).

**Elapsed:** 2026-09-27, about 18:40 to 19:05 +0800, ≈ 0.4 h wall clock. That covers pre-flight, build,
mutation checks, manual migration runs and this report.

## 1. Column contract — `inbox/po/`

One file per PO: `SAMPLE_po_PO-YYYY-NNN.csv` (SAMPLE) or `po_PO-YYYY-NNN.csv` (ACTUAL). The PO number in
the filename must equal `po_number` on every row. Fixture: `schemas/po_header_v1.json` (source `authored`,
verified `true`). Exact columns, in order; no column may be added, removed or reordered:

| # | Column | Rule |
|---|---|---|
| 1 | `po_number` | `^PO-\d{4}-\d{3}$`; equals the filename's number |
| 2 | `supplier_ref` | an existing supplier in this dataset |
| 3 | `po_date` | ISO date |
| 4 | `target_delivery_date` | ISO date, not before `po_date` |
| 5 | `currency` | equals the supplier's currency, and is `TWD` in this slice |
| 6 | `payment_terms` | free text, required |
| 7 | `incoterm` | the G-0 enum: EXW FCA CPT CIP DAP DPU DDP FAS FOB CFR CIF |
| 8 | `quote_ref` | required, non-blank |
| 9 | `status` | `draft` · `sent` · `acknowledged` · `cancelled` |
| 10 | `line_no` | 1…n, no gaps, no repeats |
| 11 | `sku` | an existing product |
| 12 | `qty_pieces` | whole pieces, > 0 |
| 13 | `unit_price_twd` | per piece, > 0, at most 4 dp |
| 14 | `setup_charge_twd` | ≥ 0, at most 4 dp |
| 15 | `line_total_twd` | exactly `qty_pieces × unit_price_twd + setup_charge_twd` |
| 16 | `min_order_qty_pieces` | blank, or whole pieces; `qty_pieces` must be at least this |
| 17 | `artwork_ref` | optional (blank allowed) |
| 18 | `evidence_ref` | required |

Columns 1–9 are header-level and repeat on every line; they must agree across lines (the ig_deals
pattern). **There is no unit column** (I-2): a file carrying one is refused as a header mismatch, so no
column can claim a unit other than the piece.

Command: `python manage.py import_po --file <path> [--commit]`. Dry-run is the default.

## 2. Every refusal message

PO intake (`ops/file_intake.py` `import_po`). `<n>` is the PO number and `<k>` the line number.

| Rule | Message |
|---|---|
| filename | `Unclassified po filename: <name>` · `Filename <name> is SAMPLE; application dataset_kind is ACTUAL` (and the reverse) |
| header | `Header mismatch in <file>; expected po v1 exact columns; missing=[…]; added=[…]; order_changed=…` |
| empty | `PO file <name> has no lines` |
| number | `po_number must match ^PO-\d{4}-\d{3}$: <value>` · `po_number <x> does not match filename PO number <n>` |
| header agreement | `PO <n> has conflicting <field> across lines` |
| line numbers | `PO <n> line_no must be an integer >= 1` · `PO <n> repeats line_no <k>` · `PO <n> has line_no gaps` |
| unknown supplier | `unknown supplier_ref: <ref>` |
| unknown SKU | `PO <n> has unknown sku(s): <sku, …>` |
| status | `PO <n> status must be draft, sent, acknowledged or cancelled: <value>` |
| incoterm | `PO <n> incoterm is not an allowed Incoterm: <value>` |
| quote | `PO <n> quote_ref is required; a PO accepts a supplier quote` |
| dates | `PO <n> target_delivery_date <d> is before po_date <d>` · `<field> must be ISO YYYY-MM-DD` |
| required | `<field> is required` (supplier_ref, po_date, target_delivery_date, currency, payment_terms, sku, unit_price_twd, setup_charge_twd, line_total_twd, evidence_ref) |
| **I-2** pieces | `PO <n> line <k> qty_pieces must be a whole number of pieces > 0` (7.5, 0, −1, blank) · the same for `min_order_qty_pieces` |
| **I-2** price | `unit_price_twd must be nonnegative with at most 4 decimal places` · `PO <n> line <k> unit_price_twd must be a positive price per piece` |
| MOQ | `PO <n> line <k> qty_pieces <q> is below min_order_qty_pieces <m>` |
| **I-3** | `PO <n> line <k> line_total_twd <x> disagrees with qty_pieces x unit_price_twd + setup_charge_twd = <y>` |
| **I-4** | `PO <n> cannot be sent: PO blocked for SKU(s): <every blocked SKU>` (also `cannot be acknowledged`) |
| **I-6** direction | `PO <n> status cannot move from <a> to <b>` · `PO <n> status cannot move from cancelled to <b>; nothing leaves cancelled` |
| **I-6** frozen | `PO <n> supplier_ref cannot change once sent` · `… currency …` · `… quote_ref …` · `PO <n> line <k> sku cannot change once sent` · `… qty_pieces …` · `… unit_price_twd …` · `… setup_charge_twd …` · `PO <n> line <k> cannot be added once sent` · `PO <n> is cancelled and cannot change` |
| lines | `PO <n> omits existing line_no(s): <k>; a missing line is not a deletion` |
| **I-7** | `PO <n> currency <c> must equal supplier <ref> currency <c>` · `PO <n> currency <c> is refused: a non-TWD PO needs the FX ruling (Agent 2 R-2.6, IFRIC 22), which does not exist yet` |
| **I-8** | `PII detected in <column>`, checked on every column. The value is never echoed |

Products intake, v3 (I-5):

| Message |
|---|
| `products file uses header v2 (no product_type); v3 requires product_type` |
| `products file uses header v1 (pack_qty); v3 requires pieces_per_sale_unit` |
| `product <sku> product_type must be sellable or packaging` |
| `sku does not match the sellable product mapping pattern: <sku>` · `… the packaging product mapping pattern: <sku>` |
| `packaging product <sku> ingredient_ref must be NOT_APPLICABLE` |
| `sellable product <sku> ingredient_ref cannot be NOT_APPLICABLE; only packaging may carry it` |
| `product field product_type cannot change` |

Migration reverse: `Reversing G-1 refused: packaging products exist (<skus>); the pre-G-1 schema cannot
represent them.`

## 3. How I-6 is enforced in the database

Migration `ops/0012_product_type_purchase_orders` follows the H-0a pattern. The intake refuses first with
named messages; the database holds even for a direct SQL writer. Each rule below has a test that bypasses
the intake (`DatabaseEnforcementTests`).

- **`ops_purchaseorderstatus_append_only`** (BEFORE UPDATE OR DELETE): the status history is
  append-only. The model's `save`/`delete` also refuse.
- **`ops_purchaseorder_forward_only`** (BEFORE INSERT OR UPDATE OR DELETE):
  - A PO is **created as `draft` only**. Every later status is a forward move.
  - Allowed moves are `draft→sent`, `sent→acknowledged`, and `draft|sent|acknowledged→cancelled`.
    Anything else raises `status cannot move from % to %`. Nothing leaves `cancelled`: any update to a
    cancelled PO raises.
  - **Every current status must be explained by a `PurchaseOrderStatus` row** (dataset, PO number, status).
  - Once `sent` or `acknowledged`, `supplier_id`, `currency` and `quote_ref` cannot change.
  - `po_number` and `dataset_kind` never change. A PO row is **never deleted** ("cancel it").
  - `currency` must equal the supplier's currency (I-7, second layer).
- **`ops_purchaseorderline_frozen_once_sent`** (BEFORE INSERT OR UPDATE OR DELETE): a line may be
  inserted, changed or deleted only while its PO is `draft`. After that, `line_no`, `product_id`,
  `qty_pieces`, `unit_price_twd`, `setup_charge_twd` and `line_total_twd` are frozen. A line cannot move to
  another PO. Non-commercial fields (`artwork_ref`, `evidence_ref`) may still be corrected.
- **CHECK constraints:** `ops_po_line_positive_pieces` (I-2) · `ops_po_line_total_identity` (I-3, exact
  numeric identity) · `ops_po_line_meets_moq` · `ops_po_line_positive_price` ·
  `ops_po_line_setup_nonnegative` · `ops_po_currency_twd` (I-7) · `ops_po_quote_ref_required` ·
  `ops_po_target_after_po_date` · `ops_po_number_shape` · `ops_po_status_allowed` ·
  `ops_po_incoterm_allowed` · unique `(dataset_kind, po_number)` and `(po, line_no)`.

**Why "created as draft".** A file first seen at `sent` still has to insert its lines, and the line trigger
accepts inserts only while the PO is `draft`. So the intake always creates the PO as `draft` with its lines,
then walks the status forward one step at a time: history row first, then the update. Each implied step is
dated `po_date`. A transition on a later re-import is dated the import day (Asia/Taipei), because the file
has no "sent on" column. PO-2026-004 (first seen at `sent`) therefore records `draft, sent`.

**I-4 applies to `sent` and `acknowledged`, not to `cancelled`.** Cancelling must always be possible,
including for a PO whose SKU has lost its declaration. I-4 is intake-only: the database cannot call the
Python guard.

## 4. Sample PO totals against the workbook

Built by script from `User Data Input/Little_Spell_PO_Master_Data.xlsx`. Vendors are mapped per
PO_FORMAT_REVIEW_01 §8 P-2: V-OEM-01 → SUP-001, V-OEM-02 → SUP-002, V-PKG-01 → SUP-003. The script asserts
that every `line_total_twd` equals the workbook's "Line Total (Excl. Tax)". `test_sample_pos_are_drafts_and_tie_to_the_workbook`
asserts the same totals from the database.

| PO | Lines (NT$ excl. tax) | Total | Workbook | Status |
|---|---|---|---|---|
| PO-2026-001 (SUP-001) | 62,000 · 66,000 · 67,000 · 36,000 | **231,000** | 231,000 | draft |
| PO-2026-002 (SUP-002) | 58,000 · 71,000 | **129,000** | 129,000 | draft |
| PO-2026-003 (SUP-003) | 100,000 · 37,000 | **137,000** | 137,000 | draft |
| PO-2026-004 (SUP-003, synthetic) | 18,000 | 18,000 | not in workbook | **sent** |

- **TS-FS-004-P:** 1,500 PK × 5 = **7,500 pieces at NT$9.0000**. That gives 67,500 + 3,500 setup =
  **71,000**, the workbook figure. MOQ 500 PK is restated as 2,500 pieces. The factor is written in the
  line's `evidence_ref`. Every other line is already in EA (= piece).
- All three workbook POs are `draft`: no sellable SKU has a declaration (the workbook said "Approved").
- **PO-2026-004** is a synthetic packaging-only PO: 10,000 × PKG-CARD-LS at NT$1.80. It reaches `sent`
  because packaging needs no declaration (I-4/I-5 passing). Its `evidence_ref` says it is not in the workbook.
- **Incoterms:** "FOB Taichung" → `FOB`, "EXW Factory (Hsinchu)" → `EXW`, "DDP Taoyuan Warehouse" → `DDP`.
  The named place is not kept, because the contract has no place column.
- **`quote_ref`:** the workbook carries no quote number, so the samples hold the visible placeholder
  `SAMPLE-PLACEHOLDER (workbook has no quote number)`. `artwork_ref` is blank for the same reason.

Open-POs report over the four samples, as of 2026-02-10:

- **Committed** = PO-2026-004 only: 10,000 pcs, NT$18,000, 6 days to target.
- **Drafts** = 8 lines, NT$497,000, never counted as committed.
- After PO-2026-004 is cancelled, committed is NT$0 and the PO leaves both sections.

## 5. The `product_type` change

- `Product.product_type`: `sellable` | `packaging`, NOT NULL, default `sellable`, CHECK
  `ops_product_type_allowed`. Every existing product migrates as `sellable`, so nothing changes for them.
- **`ops_product_ingredient_ref_shape` is replaced** (I-5): `sellable` → `UNKNOWN` or a
  `compliance/suppliers/…` path; `packaging` → exactly `NOT_APPLICABLE`. Neither type can carry the
  other's value.
- **Products header v3** = v2 + `product_type` (last column). Fixture `schemas/products_header_v3.json`
  (authored, verified). v2 and v1 files are refused by name.
- **Packaging SKU pattern** `^PKG-[A-Z]{2,8}-[A-Z]{2,4}$` (sellable keeps `TS-…`). The existing sellable
  pattern refused `PKG-MAIL-LS`, so packaging needed its own. Each type has its own pattern, so a product
  can never be re-read as the other type.
- **`assert_po_eligible`:** a packaging SKU passes if the product exists and has a supplier. The sellable
  G-0.1 rule is unchanged. The guard reads `product_type` only after `ingredient_ref == NOT_APPLICABLE`
  (which the CHECK makes packaging-only). That keeps it runnable against the pre-G-1 historical schema
  that the unchanged `ComplianceFailClosedTests` migrates through.
- Samples: `SAMPLE_products_2026-09-27.csv` is rewritten as v3 (the ten sellable SKUs plus PKG-MAIL-LS
  and PKG-CARD-LS, both packaging, factor 1, SUP-003, `NOT_APPLICABLE`). `SAMPLE_suppliers_2026-09-27.csv`
  gains SUP-002 and SUP-003 (TWD). **SUP-001 is not renamed to Precision Print Tech Co.:** G-0 refuses a
  `legal_name` change on re-import (`supplier field legal_name cannot change`), so the Railway SAMPLE
  database would refuse the renamed file.

### Existing tests changed, and why

| Test | Change | Reason |
|---|---|---|
| `ops/test_slice_g0.py` `test_identical_reimports_write_nothing_and_never_touch_ledger` | expected first-import rows `(1, 10)` → **`(3, 12)`** | the samples now hold SUP-002/003 and the two packaging SKUs |
| `ops/test_slice_g0.py` `test_supplier_pii_legal_name_change_and_missing_snapshot_are_refused` | the renamed file keeps rows 2–3; the synthetic missing supplier is **SUP-004** (was SUP-002) | SUP-002 now exists in the sample, so a one-row file would hit "missing supplier" first, and SUP-002 could not be created twice |
| `ops/test_slice_g0.py` `test_po_guard_names_all_then_only_the_remaining_nine` | the SKU list is filtered to `product_type="sellable"` | under I-5, packaging SKUs pass with product + supplier, so they are no longer in the blocked list |
| `ops/test_slice_u.py` `test_v1_unit_headers_are_refused_by_old_and_required_field_names` | expected text for products `v2 requires` → **`v3 requires`** (counts and ig_deals stay v2) | the products manifest is now v3; the message names the current version |

No other existing test changed. `ComplianceFailClosedTests` is unchanged and passes.

## 6. Tests added (`ops/test_slice_g1.py`, 30) and watched failing

I-1 is checked in **every** G-1 test: a cleanup asserts that the LedgerEvent, JournalLine, InventoryMove
and WacPosition counts are unchanged. `test_the_ledger_counter_is_not_blind` proves that counter sees a
new row.

**Mutation checks.** Each rule was disabled, or its migration piece removed, and its tests went red:

| Rule disabled | Result |
|---|---|
| I-1: an InventoryMove written on status move | 1 failure |
| I-2: intake whole-pieces check | 4 failures |
| I-3: intake identity check | 1 failure |
| I-3: DB CHECK neutralised in 0012 | 1 failure |
| I-4: eligibility call | 2 failures |
| I-5: packaging branch in the guard | 2 errors |
| I-5: DB CHECK loosened in 0012 | 2 failures |
| I-6: intake frozen fields | 7 errors |
| I-6: intake forward-only | 2 errors |
| I-6: PO trigger removed | 5 failures |
| I-6: line trigger removed | 1 failure |
| I-6: history append-only removed | 1 failure |
| I-7: currency check | 1 failure |
| I-8: `refuse_pii` | 4 failures |

Also covered: an identical re-import writes zero rows (all four samples); dry-run writes nothing;
draft → sent with undeclared sellable SKUs is refused naming all four; the same PO passes once cleared; a
packaging-only PO reaches `sent`; the three sample totals; a cancelled PO disappears from committed; the
report's HTML carries the SAMPLE banner and the CSV has `SAMPLE_` plus per-figure provenance; the admin is
read-only with the filters.

**Migration by hand (PostgreSQL 16.2):**

- On a database built at `03cab60` with the SAMPLE suppliers and products, `0012` applies. The ten products
  read `sellable UNKNOWN`. It unapplies and re-applies.
- It also applied over a fully populated U-era database (orders, moves, journal). The G-1 samples then
  imported on top: suppliers +2, products +2, POs 6/4/4/4 rows.
- Unapplying with packaging products present gives the named refusal from §2.

## 7. Open items for the orchestrator / founder

1. **Product master vs PO supplier.** The workbook buys TS-MT-005-S and TS-FS-004-P from SUP-002 (Formosa
   Foil), but the product master maps every sellable SKU to SUP-001. `Product.supplier` is immutable (G-0).
   So `assert_po_eligible` checks SUP-001's declaration for PO-2026-002. That is harmless while the PO is a
   draft, and wrong once it is sent. G-1 adds no rule for this. It needs a ruling: one supplier per SKU, or
   a SKU–supplier link.
2. **Quote numbers and artwork.** The workbook has neither. The samples carry a visible placeholder
   `quote_ref` and a blank `artwork_ref`. A real PO needs the printer's quote number.
3. **Incoterm place and FOB.** The named place is dropped. PO_FORMAT_REVIEW_01 notes that FOB is a sea
   term used here for a domestic truck; the founder's term is carried as given.
4. **Two small rules added beyond the prompt:** `unit_price_twd > 0` (a zero-price line has no committed
   value), and the packaging SKU pattern (§5).
5. **Status-history admin** filters on status only; that model holds `po_number`, not a supplier or SKU key.
6. **`inbox/po/`** lives outside `app/` and was not created (WRITE ONLY INSIDE app/).
7. Business tax (P-5), deposits (P-4) and setup-charge treatment (P-3) remain open. The report states
   "excl. tax".
