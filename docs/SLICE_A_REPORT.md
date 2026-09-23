# Slice A report — sample-data Etsy mechanism

Date: 2026-09-23. Scope: `app/` only. This slice emits operational events and writes
no accounting journal, account, posting rule, importer output file, or real customer
record. The database still begins in `dataset_kind=SAMPLE`.

## Preflight and source reliability

All seven named preflight files existed and were opened before implementation.
`../inbox/etsy/README_DO_NOT_INGEST.md` defines the filename quarantine. The
two sample files' current SHA-256 values are:

| File | Current SHA-256 | §3 recorded header fingerprint |
|---|---|---|
| `SAMPLE_etsy_orderitems_2025-12.csv` | `bf1ff8b48ae6420c75e13a3a30f1a5a80c13aa755888260d72a1f11bb031c74d` | `96dfd8ec3efa28254753834fc4a9d099e7b316571d054c52fb18d812ece9b31b` |
| `SAMPLE_etsy_statement_2025-12.csv` | `970f0cc05c80e709dafa15325a7c20733f0a21ed81fe36c0f4eb0a1e97ec07a8` | `f29820b8c1b824663586b0d30e564f467d05e233e2ca446f7e4502cf52d9403e` |

The §3 values match neither current file according to the handoff. They are
described there as header fingerprints, so they must **not** be treated as verified
file digests. The handoff calls §3 v0.9 and unverified, while the actual §3 heading
says v1.1 and its text claims `verified:true`. That contradiction remains in the
owner's contract; this implementation follows the task's explicit `verified:false`
brake. Both sets of hash values are recorded in the local JSON fixtures. No
external contract or sample file was changed.

## Implemented controls

- Filename quarantine runs before opening CSV: `SAMPLE_*.csv` is SAMPLE; only the
  two specified `etsy_*_YYYY-MM.csv` forms are ACTUAL; all others are refused.
  The filename kind must match `core_datasetsettings.dataset_kind`.
- Exact ordered headers are pinned in `schemas/etsy_*_header_v1.json`; a rename or
  reorder refuses. `--commit` refuses while either matched fixture is unverified.
- `Product`, `Channel`, `Order`, `OrderLine`, `Shipment`, `InventoryMove`, and
  `LedgerEvent` are migrated. Supporting statement-period/row tables preserve
  statement provenance and period multiset digests. Imported rows and emitted
  events carry source filename and dataset kind. Product unit is DB-checked `PK`;
  `pack_qty` is an attribute. All inventory quantities are packs. `ops_on_hand` is
  a view over signed moves, with no stored on-hand column.
- DB constraints enforce order-channel uniqueness, event idempotency uniqueness,
  allowed and mandatory discount funder, money and movement signs, gross identity,
  line totals, and `ship_date` on dispatched shipments. A database trigger rejects
  revenue/COGS events without dispatch evidence, including direct inserts. Another
  trigger rejects new ops events in a `CLOSED` ops period. The journal-line sign and period triggers
  specified by build-plan §3.4 are Slice B work: those tables do not exist and
  were expressly forbidden in this slice.
- The importer reads UTF-8 CSV with a real CSV parser; pins two date formats;
  treats `--` as null; assumes `Asia/Taipei` midnight because exports contain no
  time or zone; and flags dates at period boundaries. USD and the explicit country
  table are the currently admitted currency/destination mappings.
- `order.placed` uses gross before discount, strips platform-remitted sales tax
  into its payload, and requires a founder-maintained coupon funder mapping for
  every positive discount. The importer never infers a funder. Statement Sale rows
  control gross and emit no event. Fee rows emit additive `order.fees_assessed`
  events. Listing Fee emits period `cost.recorded` with
  `category=platform_listing_fee` and `settled_via=etsy_rail`. A negative Deposit
  emits positive-amount `settlement.received`; positive Deposit needs separate
  reversal evidence. A fee without a same-period Sale is a named reconciling item.
- Every catalogue ops type is admitted by the event emitter (22 of 22); it writes
  `LedgerEvent` only. The sample source automatically emits six types:
  `order.placed`, `order.shipped`, `order.cogs_relieved`,
  `order.fees_assessed`, `cost.recorded`, and `settlement.received`.
  Cancellation, refund and settlement-reversal service paths require synthetic
  external evidence; the sample provides no rows for them.
- Statement row keys use content hashes plus an occurrence index within identical
  groups. A second identical period inserts no rows/events; a changed period
  digest refuses rather than silently merging. Changed existing order facts also
  refuse. Import is atomic, and dry-run inserts nothing.

## §3 contract coverage and unresolved parts

| Section | Status | Gap or assumption |
|---|---|---|
| 3.1, 3.3 gross reconciliation | Implemented | Shipping-discount gross reconstruction has no matching Sale row in the sample; flagged, not claimed verified. |
| 3.2 order-item mapping | Partial | Identity, quantities, prices, discounts, shipping, tax, destination, shipment date and SKU are implemented. No customer/PII table was requested, so Buyer and address fields are deliberately not stored. `Date Paid`, coupon-description cross-check, variations and raw `Order Type` staging are not implemented. |
| 3.4 line identity and dispatch | Partial | `Transaction ID` is unique; `Date Shipped` creates a dispatched shipment and gates recognition events. Current and previously imported orders without a Sale are RISK at 35 days and BLOCK at 60 days as of the statement month-end. Tracking and duty evidence are absent. |
| 3.5 coupon funding | Implemented for seller/platform/none | The file is founder-owned and absent. No funder can be guessed from sample arithmetic. Mixed funding in the older §3 mapping is incompatible with frozen Addendum B.2's three-value CHECK and is refused pending a contract ruling. |
| 3.6 parsing | Implemented for pinned sample shapes | The `Asia/Taipei` midnight timezone is an assumption; founder confirmation D-33 remains open. Other currencies, country names and statement row types refuse rather than adapt. |
| 3.7 statement mapping | Partial | All seven present row types are parsed. Sale controls gross, four fee kinds and Listing Fee emit, Deposit emits degraded settlement. Bank value date and credit reference, full payout-composition evidence, tax-details treatment, refund and conversion rows are absent. |
| 3.8 idempotency | Implemented | Stable order/line keys and statement multiset digest; changed period needs founder review. The source has no statement row ID, so identical same-day fees remain indistinguishable at row level. |
| 3.9 schema drift | Partial | Exact-header refusal reports added/missing/reordered column names; there is no automated mapping proposal. Fixtures remain unverified, so production commit is blocked. |
| 3.10 absent events | Explicitly withheld | No source readers for payment route, PO/receipt/landed cost, inventory count/damage, carrier duty/freight, or payout reversal. The emitter accepts all frozen types, but a generic emitter is not evidence that those business transitions occurred. |

The importer also requires counted stock before recording shipped inventory moves.
This is stricter than the sample alone can satisfy; a real product master and opening
count must be loaded through an authorised future path before any committed import.
The sample POC uses synthetic products and opening moves in isolated tests only.

## Sample coverage and verification

The sample has five one-line orders and ten statement rows. It contains **no**
refund, cancellation, payout reversal, domestic Taiwan sale, or multi-line order.
Their parser/transition paths were exercised with synthetic tests, not sample data.
Nonzero sales tax and a second statement-period digest were also tested
synthetically. No landed cost exists, so COGS event amounts remain provisional/null.

Test output: `python manage.py test --verbosity 1` — **75 tests, OK**;
`python manage.py makemigrations --check --dry-run` — **No changes detected**;
`python manage.py check` — **no issues**. Tests assert identifiers and counts
and never render customer rows into public Actions logs.

## Remaining release gate

`verified:false` is intentional. `--commit` cannot run against these fixtures in
normal application use. The current mechanism demonstrates parsing, refusal,
idempotency, event emission and database checks on synthetic/sample data. It does
not validate actual sales numbers or authorize import of real customer data.
