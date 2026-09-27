# Slice G-0 — supplier master, product master intake, and product compliance flag

**Date:** 2026-09-27  
**Dataset:** SAMPLE  
**Scope:** reference-data intake only. No ledger event, posting rule, account, PO, lot, goods receipt, form, or Instagram path was added. The catalogue remains at 28 events, frozen v1.5.

## Pre-flight and the prior Product write path

Every required source was present and opened before implementation. The frozen catalogue header is exactly:

> `# \`ledger_event\` CATALOGUE — FROZEN v1.5`

A repository-wide search for `Product.objects.create`, `get_or_create`, `update_or_create`, `bulk_create`, and `Product(` found no production seed or importer. Before this slice, Product rows reached the database only through direct ORM creation in automated test setup. The production Etsy and count intakes only looked Product rows up. There was therefore no loader to extend; G-0 adds the first production Product intake.

## What was built

`Supplier` is a `Provenance` subclass keyed by `(dataset_kind, supplier_ref)`. It stores only the nine specified fields and has no contact person, email, phone, or address field. `SupplierChange` records each permitted field change with the supplier reference, field, old value, new value, source filename, dataset kind, and evidence reference.

`Product` was extended rather than replaced. It now has a nullable Supplier foreign key and `ingredient_ref`, defaulting to `UNKNOWN`. Product intake always writes `uom=PK`; there is no UOM input column. `ProductComplianceChange` records every `ingredient_ref` transition, including a withdrawal from a document path back to `UNKNOWN`.

The two management commands are `import_suppliers --file ... [--commit]` and `import_products --file ... [--commit]`. Both validate and report the planned write count in dry-run mode, and write only when `--commit` is present.

`ops/compliance.py` supplies the unused-by-design G-1 guard. `assert_po_eligible(skus)` evaluates the complete requested set and raises one `PoBlocked` listing every missing SKU, SKU with no supplier, SKU whose `ingredient_ref` is `UNKNOWN`, or SKU whose supplier has no declaration.

`ops/pii.py` supplies the shared `refuse_pii(row, columns)` boundary. Supplier and Product intake invoke it over every declared column before field parsing. It refuses email-shaped values and whitespace/start-delimited handles without echoing the sensitive value.

Supplier, SupplierChange, and ProductComplianceChange use `ReadOnlyAdmin`. Supplier has country, tax-invoice capability, and declaration-on-file filters. Product shows supplier and ingredient reference and has an `ingredient_ref = UNKNOWN` yes/no filter. The existing every-model read-only test automatically includes all three new models.

## Manifest registry and Slice F preservation

The former `manifest()` two-kind conditional was replaced with a registry of zero-argument manifest builders. `register_manifest(kind, builder)` is the extension point: a later slice can register another manifest without changing dispatch logic. Receipts, counts, suppliers, and products are registrations in that registry.

The `IntakeManifest` gained an optional strict SAMPLE filename expression. It is unset for receipts and counts, preserving their existing SAMPLE classification byte-for-byte; suppliers and products use it to enforce their dated filenames. The receipt and count builders preserve the same headers, optional columns, verification state, ACTUAL expressions, targets, events, natural keys, key derivation, and payload builders as before.

Proof:

- The unchanged `ops.test_slice_f` and `acct.test_slice_f` suites ran together with the new G-0 suite: 20 tests passed in the isolated fallback run.
- The fallback generated the schema from current models and used SQLite because the project migrations and audit SQL are PostgreSQL-specific. The required native PostgreSQL run could not start: no service was listening at `127.0.0.1:5432`. This is an environment limitation, not claimed as a PostgreSQL pass.
- `manage.py check`, Python compilation, `git diff --check`, and `makemigrations --check --dry-run` passed; migration drift was zero.

## Authored versus observed schema fixtures

Every fixture loaded by `ops.file_intake.load_schema()` must now declare `source` as exactly `authored` or `observed`; omission or another value is refused. The receipt and count fixtures were updated with the authored classification without changing their verification flags or intake behavior.

Supplier and Product formats are application-owned contracts, not third-party exports. Their fixtures therefore say `"source": "authored"` and `"verified": true`. `_reference_manifest()` additionally insists that these two fixture types are authored, so relabelling one as observed is refused even if it remains verified. A dedicated test proves that boundary. A future observed third-party fixture can use `source: observed` and remains subject to its independent verified-header gate; the two meanings cannot be silently conflated.

## Refusal paths and exact diagnostics

Dynamic values are shown in angle brackets. These messages are raised as `ImportRefused` (and management commands surface them as command errors).

### Shared source boundary

| Boundary | Exact diagnostic |
|---|---|
| Unknown registry key | `Unknown intake kind <kind>` |
| Unclassifiable name | `Unclassified <kind> filename: <name>` |
| SAMPLE/ACTUAL mismatch | `Filename <name> is <kind>; application dataset_kind is <kind>` |
| Missing/invalid fixture provenance | `<kind> schema fixture must declare source as authored or observed` |
| Reference fixture not authored | `<kind> schema fixture must have source authored` |
| Unverified commit | `Cannot --commit: <kind> schema fixture is unverified` |
| Header mismatch | `Header mismatch in <name>; expected <kind> v1 exact columns; missing=<...>; added=<...>; order_changed=<...>` |
| Bad column count | `Wrong CSV column count in <name>` |
| Bad encoding/CSV | `Cannot parse UTF-8 CSV <name>: <exception type>` |
| PII | `PII detected in <column>` |
| Required blank | `<field> is required` |

### Supplier snapshot

| Boundary | Exact diagnostic |
|---|---|
| Supplier reference | `supplier_ref must match ^SUP-\d{3}$` |
| Country | `country must be an ISO 3166-1 alpha-2 code` |
| Currency | `currency must be an ISO 4217 code in three uppercase letters` |
| Incoterm | `default_incoterm is not an allowed Incoterm` |
| Tax-invoice state | `can_invoice_to_tax_id must be yes, no or unknown` |
| Declaration path | `declaration_ref must be blank or start with compliance/suppliers/` |
| Duplicate in file | `supplier_ref repeats in one file` |
| Omitted existing supplier | `a missing supplier is not a deletion: <comma-separated refs>` |
| Immutable field drift | `supplier field <field> cannot change` |

The immutable-field message names `legal_name`, `country`, `currency`, or `default_incoterm` as applicable. Only `declaration_ref`, `can_invoice_to_tax_id`, and `payment_terms` can change.

### Product snapshot

| Boundary | Exact diagnostic |
|---|---|
| SKU pattern | `sku does not match the product mapping pattern: <sku>` |
| Pack quantity | `product <sku> pack_qty must be a positive whole number` |
| Ingredient reference | `ingredient_ref must be UNKNOWN or start with compliance/suppliers/` |
| Duplicate in file | `duplicate sku in product file` |
| Unknown supplier | `unknown supplier_ref: <comma-separated refs>` |
| Supplier lacks declaration | `product <sku>: a product cannot be cleared by a supplier with no declaration on file` |
| Immutable Product drift | `product field <field> cannot change` |

Product snapshot drift names `name`, `pack_qty`, or `supplier`; only `ingredient_ref` can change after creation.

### G-1 guard

The one aggregate exception is:

`PO blocked for SKU(s): <comma-separated sorted SKUs>`

It never stops after the first blocked SKU.

## Samples and what they cannot exercise

The requested files are under `docs/samples/`, not `inbox/`:

- `SAMPLE_suppliers_2026-09-27.csv` contains only `SUP-001`, has a blank declaration, and records tax-invoice capability as `unknown`.
- `SAMPLE_products_2026-09-27.csv` contains the mapping's ten child SKUs, their mapped pack quantities, `SUP-001`, and `UNKNOWN` for every ingredient reference.

These samples prove the authored file shape, mapping row count, default compliance block, idempotent import, and aggregate ten-SKU PO refusal. They cannot prove a real supplier identity, real payment terms, tax-invoice capability, a declaration's existence or quality, ingredient clearance, a compliant real SKU, ACTUAL filename/dataset operation, a real source-evidence chain, or PostgreSQL production behavior. They deliberately cannot exercise a successful cleared-product import without a later synthetic declaration update.

The repository guard now admits only `docs/samples/SAMPLE_*.csv` in this documentation folder; a non-SAMPLE CSV there remains refused. Its ten hook tests pass, so the required examples are committable without opening a general tabular-data bypass.

## Accounting and scope proof

The new manifests declare no events, neither importer calls `emit_event`, and no catalogue tuple, posting rule, account, LedgerEvent model, or JournalLine model was changed. The tests compare LedgerEvent and JournalLine counts before and after master imports. No PurchaseOrder, Lot, receipt-of-goods path, `po.*` emitter, writable form, or Instagram component was added.

## Verification summary

- 7 Slice G-0 tests passed in the isolated run.
- 20 combined G-0 plus unchanged Slice F tests passed in the isolated fallback run.
- Sample parsing check: one Supplier and ten Products; both fixtures were authored and verified.
- Django system check: no issues.
- Migration drift: none.
- Python compile and diff whitespace checks: pass.
- Repository safety-hook tests: 10 passed.
- Native PostgreSQL tests: not runnable locally because port 5432 refused the connection.

**Real elapsed clock time:** 6 hours 12 minutes, from 03:51 to 10:04 HKT on 2026-09-27, including review, environment diagnosis, and test fallback work.
