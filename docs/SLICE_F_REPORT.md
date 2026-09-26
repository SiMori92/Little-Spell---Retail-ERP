# Slice F — intake spine report

**Date:** 2026-09-26

**Source:** `SiMori92/Little-Spell---Retail-ERP`
**Scope:** opening-count schedule, manifest-driven intake, receipt/count files, read-only admin. No new event type or accounting account.

## Pre-flight and authority

All six required files were present before editing. `../contracts/event_catalogue_FROZEN.md` begins with **v1.4**. The working tree was clean and `origin` pointed to the public SiMori92 repository. The Addendum E amendment is implemented as `agreed_unit_cost_twd`; `line_value_twd` and `total_value_twd` are derived and checked, never silently corrected. No file outside `app/` was changed.

## F-0 — opening count

One `inventory.opening_counted` event now carries `counted_at`, mandatory `evidence_ref`, a complete `lines[]` schedule and `total_value_twd`. Each line contains `sku`, whole `qty_packs`, `agreed_unit_cost_twd`, derived `line_value_twd`, and `sellable` or `damaged_unsellable`. Emission and posting both reject a mismatched line or schedule total. Posting creates **one journal entry with one debit/credit pair per SKU**. The `1231` line carries SKU and quantity for G-3. A zero-count SKU produces a zero pair; the journal constraint admits such pairs only for the `ops:opening-count|` source with the appropriate `1231`/`3111` accounts. The inventory-move constraint admits a zero opening move with zero value. `apply_wac`, G-3 and the inventory report read the schedule. The once-per-dataset rule remains.

## F-1 — shared spine and Slice A regression

`ops/intake.py` owns filename classification, exact declared header variants, the verified-fixture gate, and a manifest declaring target models, event types, payload builders and natural-key derivation. Etsy's existing parser and persistence remain intact; its schema read and quarantine use the shared controls, while its payload construction and event keys are declared through the Etsy manifests. The legacy `quarantine_file`, `_read_csv`, `load_schema`, `ImportRefused` and `import_etsy` interfaces remain available.

| Slice A behavior retained | Proof |
|---|---|
| SAMPLE/ACTUAL filename separation and unknown-name refusal | `ops.test_slice_a.FilenameQuarantineTests`; `ops.test_slice_f.FileIntakeTests.test_unclassified_names_and_unverified_fixtures_refuse_every_kind` |
| Exact Etsy order/statement headers, UTF-8 CSV parsing and unverified `--commit` refusal | `ops.test_slice_a.ImportControlTests.test_header_mismatch_refused_before_rows_are_parsed`, `test_commit_refused_while_fixture_unverified` |
| Etsy order/transaction natural keys, statement multiset identity, no duplicate insert/event on re-import | `ops.test_slice_a.ImportControlTests.test_reimport_same_files_inserts_zero_rows_and_events`, changed-export tests |
| Etsy's 22 operational catalogue event types and dispatch evidence | `ops.test_slice_a.ImportControlTests.test_all_22_ops_catalogue_types_are_emittable_without_posting`, dispatch tests |
| Safe output and provenance columns | `ops.test_slice_a.ImportControlTests.test_fixture_contains_no_customer_fields`; model and new intake tests |

The new fixture files are `schemas/receipts_header_v1.json` and `schemas/counts_header_v1.json`. Both are deliberately `verified:false`. New `--commit` calls refuse until real source headers have been checked; tests temporarily mark them verified in memory only.

### Intake columns and posting alignment

| Kind | Input column | Validation and posting use |
|---|---|---|
| Receipt | `occurred_on` | ISO date becomes the TWD event date and journal period; ACTUAL file month must match. |
| Receipt | `category` | One of advertising, rent, software, professional, utilities, wages, bank_fee, other; maps to `cost_recorded` debit. Etsy listing fees stay on statement rows. |
| Receipt | `amount_twd` | Positive TWD with at most two decimals; becomes nonnegative `amount_minor` for `translated`. |
| Receipt | `settled_via` | `payable` or `bank`, matching the `2173` or bank credit in `cost_recorded`. |
| Receipt | `evidence_ref` | Mandatory natural key per dataset, hashed into a stable event key; retained in payload and source row. |
| Receipt | `description` | Mandatory, retained as source context; never printed by the command. |
| Receipt | `channel_attribution` (optional column) | Required for advertising and restricted to etsy/meta/other, matching `6141`/`6142`/`6143`. |
| Receipt | `bank_account` (optional column) | Allowed only for bank settlement; must resolve to a nonreserved asset account. Defaults to posting rule's `1121`. |
| Count | `counted_at` | One ISO date for every line; event date and ACTUAL filename date must agree. |
| Count | `evidence_ref` | Mandatory and identical on every line; count natural key per dataset, hashed into stable keys. |
| Count | `sku` | Unique product SKU; the file must cover every product master SKU, including explicit zeroes. |
| Count | `qty_packs` | Nonnegative whole packs; opening move and `1231` journal quantity. Later counts may only reduce posted WAC/on-hand stock. |
| Count | `agreed_unit_cost_twd` | Nonnegative exact four-decimal cost; opening `line_value_twd = qty × cost`. On later adjustment counts it remains source evidence, while the posting rule values the reduction at WAC. |
| Count | `condition` | Exactly sellable or damaged_unsellable; retained on each count line and opening payload. |

Every inserted Receipt, StockCount, StockCountLine and InventoryMove row has `source_filename` and `dataset_kind` columns. Natural keys come from the receipt/count evidence reference plus dataset, and from SKU within a count; no row number, filename or import timestamp participates. Same-file re-import inserts zero rows and emits zero events. A changed row under the same evidence key is refused. The new commands default to dry-run and print only counts.

### Refusal paths and messages

| Boundary | Diagnostic (or identifying phrase) |
|---|---|
| Unknown or cross-dataset filename | `Unclassified <kind> filename`; `Filename <name> is <kind>; application dataset_kind is <kind>` |
| Unverified fixture or malformed CSV | `Cannot --commit: <kind> schema fixture is unverified`; `Header mismatch`; `Wrong CSV column count`; `Cannot parse UTF-8 CSV` |
| ACTUAL file/date disagreement | `receipt occurred_on is outside filename period`; `counted_at disagrees with count filename date` |
| Receipt evidence, amount, category or route | `receipt evidence_ref is mandatory`; `receipt amount_twd must be positive`; `receipt category is unmapped; platform_listing_fee belongs to an Etsy statement`; `receipt settled_via must be payable or bank; etsy_rail is not a receipt route` |
| Receipt attribution/bank | `advertising receipt requires channel_attribution=etsy, meta or other`; `bank_account requires settled_via=bank`; `bank_account is not an active asset account` |
| Receipt duplicate/drift | `receipt evidence_ref repeats in one file`; `Previously imported receipt evidence_ref has changed` |
| Count date/evidence/coverage | `counted_at must be one date for the whole count schedule`; `count evidence_ref is mandatory`; `count file omits active SKU(s): ...; use explicit zero rows`; `count file repeats a SKU`; `count file has unknown SKU(s)` |
| Count quantity/cost/condition | `qty_packs must be a nonnegative whole number; blank is unknown`; `agreed_unit_cost_twd must be ...`; `condition must be sellable or damaged_unsellable` |
| Count arithmetic and repeat | `line_value_twd disagrees with quantity and cost`; `total_value_twd disagrees with sum of lines`; `opening count fires once per dataset`; `Previously imported count evidence_ref has changed` |
| Adjustment | `opening count must be posted before adjustment intake`; `a receipt is needed, not an adjustment`; `inventory adjustment lacks sufficient SKU WAC stock`; `WAC changed since count intake` |

## F-2 — read-only admin

All ops and acct models are registered with `has_add_permission`, `has_change_permission` and `has_delete_permission` returning false. Lists show IDs, SKU, account code, event type, period, status and provenance rather than buyer names or addresses. Search uses operational keys. `ops.test_slice_f.ReadOnlyAdminTests` checks every registration and permission, attempts every add URL, and attempts a representative change POST.

## Verification and limits

The existing Slice A tests and new schedule, intake and admin tests passed in [GitHub Actions run 36250665474](https://github.com/SiMori92/Little-Spell---Retail-ERP/actions/runs/36250665474) against PostgreSQL. Local `manage.py check`, compile and migration-drift checks passed. Local PostgreSQL was not running during this task, so the database-backed suite was verified in Actions rather than on this Mac.

Synthetic SAMPLE tests cannot verify actual receipt header formats, photographic evidence quality, physical count completeness, damaged stock handling, founder-agreed costs, or real WAC timing. The product model has no active flag, so “every active product” is implemented as **every Product row**. The frozen catalogue records `damaged_unsellable` but has no separate availability account or stock class; a positive damaged count still contributes to the existing per-SKU on-hand view. That is a contract/operational gap for a founder ruling, not a guessed intake rule. No parent contract file was changed.

**Elapsed hands-on build/review time:** 0.5 hours, from 22:44 to 23:14 Hong Kong time on 2026-09-26.
