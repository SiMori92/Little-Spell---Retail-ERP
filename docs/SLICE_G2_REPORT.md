# Slice G-2 report — receive stock at landed cost, by three-way match

PROMPT 12. SAMPLE mode. **This slice makes `po.received` reachable for the first time.** Catalogue v1.7,
still 28 event types; no event is added, removed or renamed.

**Branch and commits:** built on `claude/tattoo-ledger-g2-three-way-601241`, cut from `main` at `3243cf7`
(`git log -1` confirmed `3243cf7` before work started), and fast-forwarded onto `main`. Code commit
**`68aaeb6`**. This report is the next commit on the same line. As in G-1, the work was done in the session
worktree and landed on `main` by fast-forward only, so the history on `main` is the same as committing there
directly.

**CI (PostgreSQL 16 service, no SQLite):** run **`36318472379`** on `68aaeb6`: **270 tests, OK** (every step green: repository guards, pre-commit guard tests, `check`, `check --deploy`, `makemigrations --check`, `migrate`, grants, `collectstatic`)
(<https://github.com/SiMori92/Little-Spell---Retail-ERP/actions/runs/36318472379>). Local runs on
PostgreSQL 16.2 (the bundled `pgserver` binary, port 5433) gave **270 tests, OK**.

**Elapsed:** 2026-09-27, 19:56 to 20:20 +0800, about 0.4 h wall clock. That covers pre-flight, the build,
the mutation runs, the migration runs by hand and this report.

## 0. Pre-flight

| File | Result |
|---|---|
| `contracts/event_catalogue_FROZEN.md` | **v1.7**, Addendum G with G.5 present. Quoted in full in §1 |
| `contracts/acct_open_decisions.md` | Rev. 5 body present (R-1, R-3 in rev. 4; Addendum G review, C-1…C-4, fixture B in rev. 5). **Note:** its frontmatter still says `version: 1.4` |
| `contracts/acct_data_contract.md` | **v1.2.** §5.4: non-creditable input tax *"is **capitalised into that PO line's landed cost**"*. F-1 has landed |
| `state/coa.csv` `1268` note | Known stale (Agent 2 F-7). Not used; §5.4 v1.2 governs (G.5.7) |
| `PO_FORMAT_REVIEW_01.md` | §4 and the F-6 update (deposit column; damaged separate from short, with a credited flag) read. Both are in the formats below |
| `acct/posting.py` `po_received`, `ops/models.py` `PurchaseOrder*`, `ops/file_intake.py`, `docs/SLICE_G1_REPORT.md` | Read |

**One prompt statement did not match the gated samples.** The prompt calls PO-2026-003 "(packaging, sent)".
The G-1 sample `SAMPLE_po_PO-2026-003.csv` is **draft**, and a G-1 test asserts that. I did not change it.
G-2 adds `docs/samples/sent/SAMPLE_po_PO-2026-003.csv`: the same file with `status = sent`, which is the
ordinary G-1 send step. The G-2 tests import both files in order.

## 1. Addendum G, quoted in full (including G.5)

Verbatim from `contracts/event_catalogue_FROZEN.md` v1.7, from its heading to the end of the file:

> # ADDENDUM G · 2026-09-27 · v1.7 — `po.received`, as the purchase flow actually needs it
>
> **Ruled by Agent 0 under §6.4.** Accounting basis: Agent 2's rulings **R-1** (setup and non-creditable tax
> are capitalised, line-direct) and **R-3** (damage on arrival goes to `5121`, never to WAC), both in
> `contracts/acct_open_decisions.md` rev. 4.
>
> ## G.1 The payload
>
> | Field | Meaning |
> |---|---|
> | `sku_receipts[]` | one row per PO line received: `sku`, `qty_pieces` (**good pieces only**), `landed_cost_twd`, `inventory_account` = `1231` for `product_type = sellable`, `1233` for `packaging` |
> | `damaged_on_arrival[]` | optional: `sku`, `qty_pieces`, `landed_cost_twd`, for damaged pieces **the supplier did not credit**. Credited pieces are not invoiced and do not appear |
> | `tax_twd`, `tax_creditable_twd` | **both required**, `0 ≤ creditable ≤ tax`. The regime is a **given input**, never assumed (R-1). The non-creditable remainder is **inside** the SKU landed costs |
> | `landed_components_twd` | unchanged six keys. `product` = Σ `1231` rows · `packaging` = Σ `1233` rows · `supplier` = the supplier invoice total including tax · `freight` = carrier freight billed separately (`2172`) · `duty` · `in_transit` |
> | `po_number`, `receipt_no`, `invoice_no`, `gui_no` | traceability. `gui_no` may be blank when the supplier issues no 統一發票; the tax is then non-creditable, and `tax_creditable_twd` must be 0 |
>
> ## G.2 The entry
>
> Dr `1231` per sellable SKU (`sku`, `qty_delta_pieces`) · Dr `1233` per packaging SKU (`sku`, `qty_delta_pieces`) ·
> Dr `5121` per damaged SKU (`sku`; **no quantity enters WAC**) · Dr `1268` `tax_creditable_twd` =
> Cr `2171` `supplier` · Cr `2172` `freight` · Cr `2192` `duty` · Cr `1232` `in_transit`.
> **It must balance to the NT$0.0001. There is no rounding account (A7).**
>
> ## G.3 Rules
>
> 1. Landed cost of a PO line = invoiced line amount (pieces × unit price + setup) + that line's share of
>    supplier-billed freight + that line's share of non-creditable tax, **both shares allocated by line value**.
> 2. The per-piece figure is derived from the line total ÷ (good + uncredited damaged pieces). Damaged pieces carry
>    their full share, including setup (R-3.7). Allocation is exact to 4 dp: any remainder goes to the last line
>    and the sum is asserted. It is never plugged.
> 3. `po.received` fires only on a **three-way match**: a PO at `sent`/`acknowledged`, a goods receipt and a
>    supplier invoice that agree. An unmatched receipt or invoice posts nothing and is **listed**, never silently
>    held.
> 4. Supplier deposits (`1266`) are **not** in this addendum. An invoice applying a deposit is refused until the
>    deposit events are ruled (with G-3).
>
> ## G.5 · Amendment 2026-09-27 — Agent 2's review, corrections C-1…C-4 accepted
>
> Agent 2 (`acct_open_decisions.md` rev. 5) confirmed Addendum G against R-1 and R-3 **in substance** and named four
> gaps. **C-3 was an orchestrator defect: G.2 credited carrier freight and duty but G.3.1 never put them into cost, so
> the entry could not balance on such a PO.** All four are accepted:
>
> 1. **The identity (C-2), asserted at emission to NT$0.0001:**
>    `product + packaging + Σ damaged_on_arrival + tax_creditable_twd = supplier + freight + duty + in_transit`.
> 2. **Every inbound charge is allocated by line value (C-3):** supplier-billed freight, carrier freight (including
>    carrier tax while non-creditable), duty, PO-level setup and other charges, and non-creditable tax. Where an
>    invoice states tax per line, the stated tax wins. *G-2 builds supplier-billed freight and non-creditable tax
>    only. A receipt carrying carrier freight or duty is refused, naming Slice I.*
> 3. **The damaged split (C-4a):** damaged value = line landed value × damaged ÷ (good + damaged), half-up at 4 dp.
>    **Good value = line landed value − damaged value.** Never `qty × rounded per-piece`: on fixture B that route is
>    off by NT$0.4192.
> 4. **The remainder (C-4b)** of any allocation goes to the **highest PO line number** present on the receipt.
> 5. **In transit (C-1):** if `po.in_transit` has fired for a PO, its receipt must credit `2171` net of what event 16
>    already credited. *Event 16 has no emitter yet, so G-2 refuses a receipt on any PO with an in-transit event,
>    naming G-2b.*
> 6. **Tax regime:** `DatasetSettings.business_tax_regime` ∈ `unregistered` | `assessed` | `general`, default
>    `unregistered`. `tax_creditable_twd > 0` requires `gui_no` present **and** a regime other than `unregistered`.
>    A present `gui_no` never makes tax creditable on its own.
> 7. **Known stale text:** the `1268` note in `state/coa.csv` still says the 90% is "expensed" (Agent 2 F-7).
>    **Contract §5.4 v1.2 governs.**
>
> No event type is added, changed or removed. **Still 28.**
>
> ## G.4 Renumbering
>
> The wallet addendum drafted in `BUILD_TASK_03` §1.5 becomes **Addendum H (v1.8)**. The letter is assigned when a
> ruling is made, not when it is drafted.
>
> No event type is added, changed or removed. **Still 28.**

## 2. Column contracts

### 2.1 Goods receipt — `inbox/po_receipts/`

One file per (PO, receipt): `SAMPLE_grn_<PO>_<receipt_no>.csv` (SAMPLE) or `grn_<PO>_<receipt_no>.csv`
(ACTUAL). Fixture: `schemas/grn_header_v1.json` (source `authored`, verified `true`). Exact columns, in order:

| # | Column | Rule |
|---|---|---|
| 1 | `po_number` | equals the filename's PO. Header-level: must agree on every row |
| 2 | `receipt_no` | `^[A-Z0-9][A-Z0-9-]{0,31}$`; equals the filename's receipt number. Header-level |
| 3 | `received_on` | ISO date, not before the PO's `po_date`. Header-level. This is the posting date |
| 4 | `line_no` | a line of that PO; no repeats. A receipt may cover a subset of lines |
| 5 | `sku` | equals the PO line's SKU |
| 6 | `qty_pieces_good` | whole pieces ≥ 0 |
| 7 | `qty_pieces_damaged` | whole pieces ≥ 0 |
| 8 | `damaged_credited` | `yes` / `no`. Must be `no` when there is no damage |
| 9 | `short_close` | `yes` / `no` |
| 10 | `short_close_reason` | required when `short_close = yes`; must be blank otherwise |
| 11 | `evidence_ref` | required (delivery note or photo) |

Pieces **accepted** on a line = good + damaged, if not credited. Accepted must be > 0.

### 2.2 Supplier invoice — `inbox/po_invoices/`

One file per invoice: `SAMPLE_inv_<invoice_no>.csv` or `inv_<invoice_no>.csv`. Fixture:
`schemas/inv_header_v1.json` (authored, verified). Exact columns, in order:

| # | Column | Level | Rule |
|---|---|---|---|
| 1 | `invoice_no` | header | `^[A-Z0-9][A-Z0-9-]{0,31}$`; equals the filename's number |
| 2 | `gui_no` | header | blank, or a 統一發票 number: two letters and eight digits |
| 3 | `invoice_date` | header | ISO date |
| 4 | `po_number` | header | a sent or acknowledged PO |
| 5 | `receipt_no` | header | the receipt this invoice bills. One invoice per receipt |
| 6 | `line_no` | line | a line of that PO; no repeats |
| 7 | `sku` | line | equals the PO line's SKU (I-6) |
| 8 | `qty_pieces_invoiced` | line | whole pieces > 0 |
| 9 | `unit_price_twd` | line | equals the PO line exactly (I-6) |
| 10 | `setup_charge_twd` | line | equals the PO line exactly (I-6) |
| 11 | `line_amount_twd` | line | exactly `qty_pieces_invoiced × unit_price_twd + setup_charge_twd` |
| 12 | `freight_twd` | header | supplier-billed freight, ≥ 0, 4 dp |
| 13 | `tax_twd` | header | **required**, ≥ 0 |
| 14 | `tax_creditable_twd` | header | **required**, `0 ≤ creditable ≤ tax` (I-5) |
| 15 | `invoice_total_twd` | header | exactly `Σ line_amount_twd + freight_twd + tax_twd` |
| 16 | `deposit_applied_twd` | header | must be 0 (I-8) |
| 17 | `evidence_ref` | header | required (the invoice scan) |

Header-level columns repeat on every row and must agree (the ig_deals pattern). **A file that carries any
column whose name contains `carrier` or `duty` is refused by name, naming Slice I**, before the header check
(I-3). An exact-header file cannot carry one either.

Commands (dry-run by default): `manage.py import_grn --file <path> [--commit]`,
`manage.py import_supplier_invoice --file <path> [--commit]`, and
`manage.py set_business_tax_regime unregistered|assessed|general` (`DatasetSettings` stays read-only in the
admin). `inbox/po_receipts/` and `inbox/po_invoices/` are outside `app/` and were not created.

## 3. How it works

1. Each file is validated on its own and against the PO, then stored **append-only** (`GoodsReceipt` +
   `GoodsReceiptLine`, `SupplierInvoice` + `SupplierInvoiceLine`, all on the existing `Provenance` base).
2. After either file commits, the matcher looks for the other document of the same (PO, `receipt_no`).
   - **None yet:** nothing posts. The document is listed in `/reports/po-exceptions/`.
   - **Both, and they disagree:** nothing posts. The pair is listed as a *refused match* with every reason.
     The import itself succeeds: both documents are facts. Reasons are recomputed from the stored documents
     on each report run; nothing is held in a queue.
   - **Both, and they agree:** the landed values are computed (`ops/landed_cost.py`). The Addendum G payload is
     built and the G.5.1 identity asserted. The candidate is planned through the posting rule, then **one**
     `po.received` is emitted (key `po.received|<dataset>|<PO>|<receipt_no>`, dated `received_on` 12:00
     Asia/Taipei) and posted by `post_event`, the existing path. That updates `WacPosition` for `1231` rows
     through the existing mechanism. An `InventoryMove` (`received`) is written for sellable good pieces.
3. When every line of the PO has a posted receipt, the PO moves to `received`, or to `short_closed` if any
   line was short-closed. The history row is written first and dated the completing `received_on`.

**Allocation (G.5.2–G.5.4).** Line amount = invoiced pieces × unit price + setup (setup is line-direct, R-1.1).
Supplier-billed freight and non-creditable tax (`tax − creditable`) are each allocated by line amount. Each
share is half-up at 4 dp, and each charge's remainder goes to the **highest PO line number on the receipt**.
The sum is asserted. `value_receipt` also accepts a stated per-line tax, which then wins over value. **The
invoice contract has no per-line tax column**, so the intake always allocates by value today. The rule is
unit-tested for when such a column is ruled.

**Damage (G.5.3, R-3).** Damaged value = landed × damaged ÷ (good + damaged), half-up at 4 dp. Good value =
landed − damaged. The good row carries good pieces only, so damage adds no WAC quantity. Credited damaged
pieces are not invoiced (the match checks invoiced = good + damaged-not-credited) and appear nowhere.

**Posting rule (`acct/posting.py` `po_received`, the only posting rule changed).** It requires the six
components, `tax_twd` and `tax_creditable_twd`. Carrier `freight`/`duty` > 0 is refused naming Slice I, and
`in_transit` > 0 naming G-2b. It refuses creditable tax without a `gui_no`, or while the regime is
`unregistered`. It ties Σ `1231` rows to `product` and Σ `1233` rows to `packaging`, and asserts the G.5.1
identity. It posts Dr `1231`/`1233` per SKU with `qty_delta_pieces`, Dr `5121` per damaged SKU with no
quantity, Dr `1268`, and Cr `2171` (plus `2172`/`2192`/`1232`, which are zero here). `apply_wac` now moves
WAC for `1231` rows only.

## 4. Every refusal message

`<po>` is the PO number, `<r>` the receipt number, `<inv>` the invoice number and `<k>` the PO line number.
Every intake refusal writes nothing.

**Goods receipt (`ops/receiving.py` `import_grn`)**

| Rule | Message |
|---|---|
| filename | `Unclassified grn filename: <name>` · `Filename <name> is SAMPLE; application dataset_kind is ACTUAL` (and the reverse) |
| carrier (I-3) | `<file> carries carrier freight or duty (<columns>); carrier freight and duty on a receipt arrive in Slice I (catalogue G.5.2)` |
| header | `Header mismatch in <file>; expected grn v1 exact columns; missing=[…]; added=[…]; order_changed=…` |
| empty | `GRN file <name> has no lines` |
| shape | `receipt_no must match ^[A-Z0-9][A-Z0-9-]{0,31}$: <value>` · `GRN <po>/<r> line_no must be an integer >= 1` · `<field> is required` · `received_on must be ISO YYYY-MM-DD` |
| filename agreement | `po_number/receipt_no <a>/<b> does not match filename <po>/<r>` |
| header agreement | `GRN <po>/<r> has conflicting <field> across lines` · `GRN <po>/<r> repeats line_no <k>` |
| pieces | `GRN <po>/<r> line <k> qty_pieces_good must be a whole number of pieces >= 0` (same for `qty_pieces_damaged`) |
| flags | `GRN <po>/<r> line <k> damaged_credited must be yes or no` · `… short_close must be yes or no` · `… damaged_credited must be no when qty_pieces_damaged is 0` |
| nothing accepted | `GRN <po>/<r> line <k> accepts no pieces; a line with nothing received cannot carry its setup (R-1.2)` |
| **I-7** short | `GRN <po>/<r> line <k> accepts <a> of <o> ordered pieces; a short delivery closes the line: short_close=yes with a short_close_reason (multi-delivery lines arrive in G-2b)` · `… short_close=yes needs a short_close_reason` · `… short_close_reason is allowed only with short_close=yes` · `… short_close=yes but the line is not short (<a> of <o> ordered pieces)` |
| **I-7** one receipt | `PO <po> line <k> already has receipt <r>; multi-delivery lines arrive in G-2b` |
| **I-1** PO | `unknown PO: <po>` · `PO <po> is <status>; a goods receipt is accepted only against a sent or acknowledged PO` |
| **I-11** | `PO <po> has a po.in_transit event; a receipt after goods in transit arrives in G-2b (catalogue G.5.5)` |
| PO lines | `PO <po> has no line <k>` · `GRN <po>/<r> line <k> sku <a> disagrees with PO <po> line <k> sku <b>` |
| dates | `GRN <po>/<r> received_on <d> is before PO <po> po_date <d>` |
| **I-9** | `Previously imported goods receipt <po>/<r> has changed; goods receipts are append-only` |
| **I-10** | `PII detected in <column>`, checked on every column. The value is never echoed |

**Supplier invoice (`import_invoice`)**

| Rule | Message |
|---|---|
| filename / header / carrier / empty | as for GRN, with `inv`; `invoice file <name> has no lines` |
| shape | `invoice_no must match ^[A-Z0-9][A-Z0-9-]{0,31}$: <value>` · `receipt_no must match …` · `INV <inv> gui_no must be blank or two letters and eight digits` · `INV <inv> line <k> qty_pieces_invoiced must be a whole number of pieces > 0` · `<field> is required` (including **`tax_twd is required`** and **`tax_creditable_twd is required`**, I-5) · `<field> must be nonnegative with at most 4 decimal places` |
| filename agreement | `invoice_no <a> does not match filename invoice number <inv>` |
| header agreement | `INV <inv> has conflicting <field> across lines` · `INV <inv> repeats line_no <k>` |
| line identity | `INV <inv> line <k> line_amount_twd <x> disagrees with qty_pieces_invoiced x unit_price_twd + setup_charge_twd = <y>` |
| total | `INV <inv> invoice_total_twd <x> disagrees with sum(line_amount_twd) + freight_twd + tax_twd = <y>` |
| **I-8** | `INV <inv> deposit_applied_twd must be 0; supplier deposits arrive with G-3` |
| **I-5** | `INV <inv> tax_creditable_twd <c> exceeds tax_twd <t>` · `INV <inv> tax_creditable_twd > 0 requires a gui_no; a blank gui_no means the tax is not creditable (catalogue G.1)` · `INV <inv> tax_creditable_twd > 0 requires business_tax_regime assessed or general; this dataset is unregistered (catalogue G.5.6)` |
| **I-1** PO | `unknown PO: <po>` · `PO <po> is <status>; a supplier invoice is accepted only against a sent or acknowledged PO` · `PO <po> has no line <k>` |
| **I-6** | `INV <inv> line <k> sku <a> disagrees with PO <po> line <k> sku <b>` · `INV <inv> line <k> unit_price_twd <a> disagrees with PO <po> line <k> unit_price_twd <b>; a price variance is refused, not absorbed (the PO is frozen once sent)` · the same for `setup_charge_twd` |
| one invoice | `PO <po> line <k> is already invoiced by <inv>; multi-delivery lines arrive in G-2b` · `receipt <r> on PO <po> is already invoiced by <inv>` |
| **I-9** | `Previously imported supplier invoice <inv> has changed; supplier invoices are append-only` |
| **I-10** | `PII detected in <column>` |

**Refused match** (nothing posts; listed in `/reports/po-exceptions/` and returned by the import):

| Message |
|---|
| `INV <inv> against GRN <po>/<r>: invoice lines [..] do not match receipt lines [..]` |
| `INV <inv> against GRN <po>/<r> line <k>: invoiced <n> pieces but received good <g> + damaged not credited <d> = <g+d>` |
| `PO <po> is <status>; po.received needs a sent or acknowledged PO` |
| `PO <po> has a po.in_transit event; a receipt after goods in transit arrives in G-2b (catalogue G.5.5)` |
| `INV <inv> against GRN <po>/<r>: <any landed-cost or posting-rule refusal below>` |

**Landed cost (`ops/landed_cost.py`)**: `po.received identity fails: product + packaging + damaged +
tax_creditable = <l> but supplier + freight + duty + in_transit = <r> (catalogue G.5.1; no plug, no rounding
account)` · `line <k> receives no pieces` · `tax_creditable_twd must be between 0 and tax_twd` · `stated per-line
tax does not sum to tax_twd` · `per-line tax is stated on some lines but not all` · `a charge cannot be
allocated over lines of zero value` · `allocation does not sum to its total` · `nothing to allocate over` ·
`a receipt needs at least one line` · `line numbers repeat`.

**Posting rule (`po_received`)**: `PO landed components incomplete` · `required payload field <f> is missing`
(`landed_components_twd`, `sku_receipts`, `tax_twd`, `tax_creditable_twd`, `qty_pieces`, `landed_cost_twd`) ·
`PO receipt needs positive whole-piece SKU quantities` · `damaged on arrival needs positive whole-piece SKU
quantities` · `sku_receipts inventory_account must be 1231 (sellable) or 1233 (packaging)` · `carrier freight
and duty on a receipt arrive in Slice I (catalogue G.5.2)` · `a receipt after po.in_transit arrives in G-2b
(catalogue G.5.5)` · `tax_creditable_twd cannot exceed tax_twd` · `creditable input tax requires a gui_no
(catalogue G.1)` · `creditable input tax requires business_tax_regime assessed or general (G.5.6)` · `SKU landed
cost does not tie to product inventory debit 1231` (and `packaging … 1233`) · `po.received identity fails by <d>
TWD (catalogue G.5.1)`.

**PO file (G-1 intake, extended)**: `PO <po> is received and cannot change` (also `short_closed`). The unchanged
file at `sent`/`acknowledged` re-imports as a no-op. Also `PO <po> has goods received and cannot be cancelled`.

**Migration reverse**: `Reversing G-2 refused: POs have been received (<po, …>); the pre-G-2 schema cannot
represent them.`

## 5. The PO-2026-003 journal entry, line by line

GRN `R1` (received 2026-01-29) plus invoice `EP-2026-0129` (gui_no blank; tax 6,850; creditable 0; total
143,850). One `po.received`, key `po.received|SAMPLE|PO-2026-003|R1`, journal period `2026-01`:

| # | Account | SKU | qty_delta_pieces | Debit | Credit |
|---|---|---|---|---|---|
| 1 | `1233` Inventory – packaging | PKG-MAIL-LS | 15,000 | 105,000.0000 | |
| 2 | `1233` Inventory – packaging | PKG-CARD-LS | 19,800 | 38,461.5000 | |
| 3 | `5121` Shrinkage and write-off | PKG-CARD-LS | — (no quantity) | 388.5000 | |
| 4 | `2171` AP – print suppliers | | | | 143,850.0000 |
| | **Total** | | | **143,850.0000** | **143,850.0000** |

How it is built:

| | Mailers (line 1) | Cards (line 2, highest line) |
|---|---|---|
| Line amount | 15,000 × 6.5000 + 2,500 = 100,000.0000 | 20,000 × 1.8000 + 1,000 = 37,000.0000 |
| Non-creditable tax by value | 5,000.0000 | 1,850.0000 (remainder) |
| Landed | **105,000.0000 → 7.0000/pc** | **38,850.0000 → 1.9425/pc** |
| Damaged 200, not credited | — | 38,850 × 200 ÷ 20,000 = **388.5000 → 5121** |
| Good | 105,000.0000 (15,000 pcs) | 38,850 − 388.5 = **38,461.5000 (19,800 pcs)** |

Identity: 0 + 143,461.5000 + 388.5000 + 0 = 143,850.0000 + 0 + 0 + 0. PO-2026-003 moves to `received`.
No `WacPosition` or `InventoryMove` row: packaging is not WAC stock (see §8).

Payload, as stored:
```json
{
  "po_number": "PO-2026-003",
  "receipt_no": "R1",
  "invoice_no": "EP-2026-0129",
  "gui_no": "",
  "sku_receipts": [
    {
      "sku": "PKG-MAIL-LS",
      "qty_pieces": "15000",
      "landed_cost_twd": "105000.0000",
      "inventory_account": "1233"
    },
    {
      "sku": "PKG-CARD-LS",
      "qty_pieces": "19800",
      "landed_cost_twd": "38461.5000",
      "inventory_account": "1233"
    }
  ],
  "damaged_on_arrival": [
    {
      "sku": "PKG-CARD-LS",
      "qty_pieces": "200",
      "landed_cost_twd": "388.5000"
    }
  ],
  "tax_twd": "6850.0000",
  "tax_creditable_twd": "0.0000",
  "landed_components_twd": {
    "product": "0.0000",
    "packaging": "143461.5000",
    "supplier": "143850.0000",
    "freight": "0.0000",
    "duty": "0.0000",
    "in_transit": "0.0000"
  }
}
```

**Fixture B (test only).** The same PO, but the supplier's invoice also bills freight 1,050 (total 144,900):
Dr 1233 mailers **105,766.4234** (7.0511/pc derived) · Dr 1233 cards **38,742.2408** (19,800 pcs) · Dr 5121
**391.3358** · Cr 2171 **144,900.0000**. The per-piece route (19,800 × 1.9567 = 38,742.6600) is asserted to be
**not** what was posted; it differs by 0.4192.

**Sellable case (test only; SUP-001 and TS-FL-001-S declared in the test).** PO-2026-005, 5,000 × 12.0000 +
2,000 setup. General regime, `gui_no` AB12345678, tax 3,100, creditable 3,100: Dr 1231 TS-FL-001-S
**62,000.0000** (5,000 pcs; exactly the line amount) · Dr 1268 **3,100.0000** · Cr 2171 **65,100.0000**.

**WAC by hand (test).** Opening 480 pcs × 13.0000 = 6,240.0000, then the receipt above. WAC =
(6,240 + 62,000) ÷ (480 + 5,000) = 68,240 ÷ 5,480 = **12.4526/pc**. The test asserts `WacPosition` =
5,480 pcs / 68,240.0000.

## 6. Reports

- **`/reports/po-exceptions/?as_of=`** has three sections: *Received, not invoiced* (per receipt line:
  good/damaged pieces, days waiting), *Invoiced, not received*, and *Refused matches* (with every reason).
  Over the samples as of 2026-02-20 it lists **PO-2026-004 R1, PKG-CARD-LS, 10,000 good pieces, 6 days
  waiting**. The other two sections are empty.
- **`/reports/landed-cost/?as_of=`** shows each posted receipt line: good and damaged pieces, line amount, setup,
  supplier-freight share, non-creditable-tax share, landed total, per-piece landed (NT$ to 4 dp), damaged to
  5121, and good to stock. The figures over the samples are those in §5.

Both reports sit in the *Purchasing* group, carry the SAMPLE banner, and export CSV with per-figure
provenance.

## 7. Tests

### 7.1 Existing tests that needed touching

| Test | Change | Reason |
|---|---|---|
| `acct/test_slice_b.py` `test_every_postable_ops_rule_balances` (the `po.received` case) | Payload now has `tax_twd`/`tax_creditable_twd` = 0, carrier freight/duty 0 (supplier 110), and the packaging 10 as a per-SKU `1233` row | Addendum G makes the tax fields required, puts packaging on `1233` per SKU, and G-2 refuses carrier freight/duty (Slice I). The old payload is no longer valid |
| `acct/test_slice_b.py` `test_cogs_uses_running_weighted_average_per_sku` | Adds `"tax_twd":"0","tax_creditable_twd":"0"` to its synthetic receipt | Same: I-5 makes both fields required. The WAC assertions are unchanged |

No other existing test changed. `test_old_pack_payload_names_are_refused` (the `qty_packs` receipt) passes
unchanged, because row validation runs before the tax check. The Slice U historical-migration tests passed
only after `business_tax_regime` got a database default (`db_default`). They insert `DatasetSettings` through
a pre-G-2 model state, and the column must accept that.

### 7.2 Added: `ops/test_slice_g2.py`, 39 tests

| Invariant | Tests |
|---|---|
| **I-1** | receipt against a draft PO refused · invoice without receipt listed, posts nothing · disagreeing pair listed with its reason, posts nothing · differing line sets are a refused match · invoice-first and receipt-first give the same entry · PO-004 receipt without invoice listed, posts nothing · dry-run writes nothing |
| **I-2** | identity holds and is watched at 0.0001 (both `assert_identity` and the posting rule) · emission asserts it |
| **I-3** | remainder to the highest PO line number with the rows in reverse order (0.3333 / 0.3333 / **0.3334**) · stated per-line tax wins · carrier freight and duty refused naming Slice I (invoice, GRN, posting rule) · fixture B allocation |
| **I-4** | damaged sellable pieces go to 5121 and add no WAC quantity · value × ratio, never qty × per-piece · credited damage appears nowhere · fixture B per-piece route not posted |
| **I-5** | tax fields required · creditable > tax, blank GUI, unregistered regime, bad GUI refused; unregistered with a GUI capitalises the tax · posting rule refuses the same · DB CHECKs |
| **I-6** | unit price, setup, SKU, line identity and total variances refused by name |
| **I-7** | second receipt on a line refused (intake and DB unique) · short delivery must close with a reason · short-closed line capitalises setup over pieces received (98,175 ÷ 14,000 = 7.0125) and the PO goes `short_closed` · overs allowed when invoiced |
| **I-8** | deposit refused naming G-3 |
| **I-9** | identical re-import of GRN, invoice and PO files writes zero rows and zero events · re-import on a partly received PO writes nothing · changed re-imports refused |
| **I-10** | PII refused on every GRN column and on invoice columns, never echoed |
| **I-11** | in-transit PO refused naming G-2b (intake and posting rule) |
| DB | the four documents are append-only · `received` needs every line; `received` is terminal; goods block cancel · a document line must belong to its own PO |
| Figures | PO-003 entry and landed-cost figures to 0.0001 · fixture B · sellable general regime · WAC by hand |
| Reports | HTML with SAMPLE banner, CSV filename and provenance, index entries |

### 7.3 Watched failing (mutation runs)

I disabled each rule, ran `ops.test_slice_g2`, confirmed red, and restored it (`scratchpad/mutate.py`, `mutate_db.py`):

| Rule disabled | Result |
|---|---|
| I-1 PO status gate at intake | 1 failure |
| I-1 pieces agreement in the match | 1 failure |
| I-2 identity in the posting rule | 1 failure |
| I-2 identity at emission | 2 failures |
| I-3 remainder to highest line number (→ last dict entry) | 1 failure |
| I-3 non-creditable tax not capitalised | 6 failures, 9 errors |
| I-3 carrier freight/duty refusal | 3 failures |
| I-3 stated tax wins | 1 failure |
| I-4 damaged split by the per-piece route | 2 failures |
| I-4 damaged pieces added to the good quantity | 3 failures |
| I-4 WAC for 1233 rows too | 1 failure |
| I-5 regime check at intake / GUI check at intake / regime check in posting rule | 1 / 1 / 1 failure |
| I-6 price and setup equality | 4 failures |
| I-7 one receipt per line (intake) | 1 error (the DB unique catches it, unnamed) |
| I-7 short delivery must close | 1 failure |
| I-8 deposit refusal (intake) | 1 error (the DB CHECK catches it, unnamed) |
| I-9 match idempotency guard | 1 error. **First run: survived.** The PO-status check masked it on single-receipt POs, so I added `test_reimporting_a_posted_receipt_on_a_partly_received_po_writes_nothing` |
| I-10 PII on GRN / on invoice | 1 / 1 failure |
| I-11 in-transit at intake / in posting rule | 1 / 1 failure |
| DB append-only triggers removed | 4 failures |
| DB line-belongs trigger removed | 1 failure |
| DB "received needs every line" removed | 1 failure |
| DB cancel-with-goods removed | 1 failure |
| DB received-is-terminal removed | 1 failure |

### 7.4 Migration by hand (PostgreSQL 16.2)

- I built a database at `3243cf7` (G-1) with the G-1 samples imported: suppliers 3, products 12, and POs
  001–004. `core/0006` and `ops/0013` applied over it. `ops/0013` unapplied and re-applied.
- The G-2 samples then imported on top. PO-003 was sent, received and invoiced, which posted the §5 entry.
  PO-004 R1 stayed listed.
- `migrate ops 0012` with PO-003 received gives the named refusal from §4.

## 8. Open items for the orchestrator / Agent 2

1. **Fixture B's freight account.** The prompt states fixture B as **supplier-billed** freight, credited to
   `2171` (144,900). Agent 2's rev. 5 proposed a **carrier** invoice credited to `2172`. The allocated figures are
   identical, but the credit account differs. G-2 builds the prompt's version, because carrier freight is refused
   until Slice I. Agent 2 should confirm this is the intended reading.
2. **Packaging stock quantity.** Per the prompt, WAC moves for `1231` rows only. `1233` carries SKU and
   `qty_delta_pieces` on the journal line, but there is no `WacPosition` and no `InventoryMove` for packaging.
   So `ops_on_hand` does not show packaging, and `1233` is still relieved by the `packaging_twd` lump on
   `order.cogs_relieved`. Separately, the opening count (unchanged) posts every counted line to `1231`,
   packaging included. Both need a ruling before packaging is counted or relieved per SKU.
3. **Credited damage and I-7.** A supplier credit leaves the line short of the PO. With one receipt per line,
   the GRN must short-close it, and a replacement delivery has to wait for G-2b.
4. **Per-line tax column.** The allocator honours stated per-line tax, but the invoice contract has no column for
   it. Add one if a supplier ever issues a mixed-rate or partly untaxed invoice.
5. **Rules added beyond the prompt:** a PO with goods received cannot be cancelled (intake and trigger);
   `received`/`short_closed` are terminal; `received_on` may not precede `po_date`; the document-number and
   統一發票 shapes; a document line must belong to its own PO (trigger).
6. **Status timing.** `received`/`short_closed` is set when the last line's receipt **posts**, not when the goods
   arrive. A receipt awaiting its invoice leaves the PO at `sent`, and it is listed in the exceptions report.
7. **Stale texts:** the `state/coa.csv` `1268` note (F-7), and `acct_open_decisions.md`'s frontmatter version (1.4
   while the body is rev. 5).
8. **`set_business_tax_regime`** records the regime without an evidence reference, because `DatasetSettings` has
   no column for one. The regime is still Message 3's open question; the default `unregistered` forces every
   creditable figure to 0.
