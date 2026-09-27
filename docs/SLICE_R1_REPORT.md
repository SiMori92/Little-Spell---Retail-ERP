# Slice R-1 — Switch to real data

Date: 2026-09-27 HKT
Branch: `main`
Gate base: `7efdf1b`
Implementation commit: recorded after commit below
PostgreSQL CI run: recorded after the first push below
Real elapsed build time: 2.0 hours at initial report authoring

## Result

Production now starts from a separate, empty database. The flip requires a matching recorded secret
rotation, explicit opening amount and funding type, and zero SAMPLE rows in every concrete model carrying
`dataset_kind`. It posts exactly one two-line ACTUAL `owner.funds_moved` entry and flips the singleton in the
same transaction. The UAT environment and its database remain SAMPLE permanently.

The frozen event catalogue remains 28 events (22 operational + 6 manual). Etsy remains out of scope and its
two fixtures remain unverified.

## Refusal messages

The new or retained operator-visible refusals are:

```text
REFUSED: dataset_kind is already ACTUAL
REFUSED: SAMPLE rows exist in table(s): <sorted database table names>
REFUSED: no SecretRotation row exists
REFUSED: latest SecretRotation does not match the running SECRET_KEY
--amount '<value>' is not an exact decimal
--amount must be greater than zero and finite
--amount carries more than 4 decimal places (numeric(18,4))
--funding-type must be one of: capital, loan
--actor is required and cannot be blank
--evidence-ref is required and cannot be blank
REFUSED: opening rule did not produce exactly the authorised two lines
REFUSED: missing account(s): <sorted account codes>
dataset_kind is one-way: ACTUAL cannot be changed back to SAMPLE
seed is restricted to SAMPLE mode
load_uat_sample is restricted to SAMPLE mode
opening count fires once per dataset
Filename <name> is SAMPLE; application dataset_kind is ACTUAL
Filename <name> is ACTUAL; application dataset_kind is SAMPLE
Cannot --commit: orderitems schema fixture is unverified
Cannot --commit: statement schema fixture is unverified
```

Missing required CLI options are also refused by Django/argparse before command execution, for example:

```text
the following arguments are required: --amount, --funding-type, --actor, --evidence-ref
```

## Dry-run output

Empty database before rotation:

```text
PASS: dataset is not already ACTUAL
PASS: database contains no SAMPLE business rows
FAIL: a secret rotation is recorded — no SecretRotation row exists
FAIL: latest rotation matches the running SECRET_KEY — latest SecretRotation does not match the running SECRET_KEY
PASS: opening amount is positive and exact to 4 dp
PASS: funding type is capital or loan
PASS: actor is present
PASS: evidence reference is present
Dr 1121 150000.0000 TWD
Cr 3111 150000.0000 TWD
--dry-run: nothing written.
REFUSED: no SecretRotation row exists; latest SecretRotation does not match the running SECRET_KEY
```

The same empty database after `record_secret_rotation` changes the two FAIL lines to PASS and produces no
refusal. The output contains the hash neither as a value nor as part of a row representation; the key itself
is never printed or persisted.

Combined UAT database:

```text
PASS: dataset is not already ACTUAL
FAIL: database contains no SAMPLE business rows — SAMPLE rows exist in table(s): acct_journalentry, ops_goodsreceipt, ops_goodsreceiptline, ops_igdeal, ops_igdealstatus, ops_inventorymove, ops_ledgerevent, ops_purchaseorder, ops_purchaseorderline, ops_purchaseorderstatus, ops_supplier, ops_supplierinvoice, ops_supplierinvoiceline, ops_supplierpayment
PASS: a secret rotation is recorded
PASS: latest rotation matches the running SECRET_KEY
PASS: opening amount is positive and exact to 4 dp
PASS: funding type is capital or loan
PASS: actor is present
PASS: evidence reference is present
Dr 1121 150000.0000 TWD
Cr 3111 150000.0000 TWD
--dry-run: nothing written.
REFUSED: SAMPLE rows exist in table(s): acct_journalentry, ops_goodsreceipt, ops_goodsreceiptline, ops_igdeal, ops_igdealstatus, ops_inventorymove, ops_ledgerevent, ops_purchaseorder, ops_purchaseorderline, ops_purchaseorderstatus, ops_supplier, ops_supplierinvoice, ops_supplierinvoiceline, ops_supplierpayment
```

## Combined UAT figures, re-derived

The PO-002 change is caused solely by using the G-3 `sent` fixture in the combined pack rather than the Run A
`draft` fixture. No amount or quantity changed.

| Checkpoint | Figure | Old separate Run A | Combined pack | Reason |
|---|---:|---:|---:|---|
| Four POs first loaded | committed | NT$18,000 / 10,000 pcs | NT$147,000 / 20,500 pcs | PO-002 NT$129,000 / 10,500 pcs is sent |
| Four POs first loaded | drafts | NT$497,000 / 59,500 pcs | NT$368,000 / 49,000 pcs | PO-002 moved out of drafts |
| After PO-003 sent | committed | NT$155,000 / 45,000 pcs | NT$284,000 / 55,500 pcs | PO-002 is also committed |
| After PO-003 sent | drafts | NT$360,000 / 24,500 pcs | NT$231,000 / 14,000 pcs | only PO-001 remains draft |
| Full combined pack | committed open POs | n/a | NT$18,000 / 10,000 pcs | PO-002 closed, PO-003 received; PO-004 remains sent |
| Full combined pack | drafts | n/a | NT$231,000 / 14,000 pcs | PO-001 |

PO-003 landed-cost lines remain:

| SKU/account | Quantity | Landed/unit | Posted debit |
|---|---:|---:|---:|
| PKG-MAIL-LS / 1233 | 15,000 good | NT$7.0000/pc | NT$105,000.0000 |
| PKG-CARD-LS / 1233 | 19,800 good | NT$1.9425/pc | NT$38,461.5000 |
| PKG-CARD-LS / 5121 | 200 damaged | NT$1.9425/pc | NT$388.5000 |
| Supplier payable / 2171 | — | — | Cr NT$143,850.0000 |

Run B remains unchanged step by step:

| After | 1121 | 1266 | 2171 | PO-002 |
|---|---:|---:|---:|---|
| DEP-002 | -38,700 | 38,700 | 0 | sent |
| R1 + INV-A | -38,700 | 21,300 | -43,500 | sent |
| R2 + INV-B | -38,700 | 0 | -96,750 | received |
| BAL-A + BAL-B | -135,450 | 0 | 0 | closed |

Instagram remains 12 enquiries → 10 quoted (`83.3333%`) → 6 paid (`50.0000%`), with follow-ups
IG-202610-001/002/012 overdue 41/36/31 days at 2026-11-15. Repeat rate remains 2 of 4 customers (`50.0000%`).

## Tests changed

- `core/tests/test_flip_command.py` — replaced the Slice 0 stub/refusal contract with R-1 amount, funding,
  rotation, empty-database, atomic rollback, one-way, dry-run, two-line posting, seed refusal, opening count,
  ACTUAL provenance, and first-PO tests.
- `core/tests/test_secret_rotation.py` — new append-only, no-op, required provenance, digest, and no-secret-
  disclosure tests.
- `ops/test_slice_f.py` — the two obsolete receipts/counts “unverified commit refusal” assertions now prove
  both authored formats commit; Etsy's existing refusal test remains the unverified-format sentinel.
- `ops/test_slice_r1.py` — new all-11 filename-boundary test, combined loader rollback/refusal tests, and
  recomputed combined-pack report figures.
- `ops/test_slice_u.py` — R-1.1 isolates the ACTUAL migration-refusal scenario in a transaction that is
  rolled back, so teardown never attempts the forbidden ACTUAL→SAMPLE transition; the trigger remains the
  authoritative control and is not bypassed.

## Verification

Local static checks passed:

```text
python -m compileall -q core acct ops
python manage.py check
python manage.py makemigrations --check --dry-run
git diff --check
```

Local PostgreSQL execution was unavailable because no service or container runtime was running on the build
host (`127.0.0.1:5432` refused the connection). Per the build packet, the complete PostgreSQL 16 suite is run
by GitHub Actions after push; its run identifier and result are recorded above after completion.

## R-1.1 — gate evidence repair

- Corrected the opening-count test and refusal list to the real posting message:
  `opening count fires once per dataset`. The production posting message was not changed.
- Corrected `test_actual_dataset_refuses_unconditionally` using transaction rollback isolation. The test
  performs the real SAMPLE→ACTUAL transition and real migration refusal inside an outer transaction, then
  rolls that state back; teardown therefore never attempts ACTUAL→SAMPLE and no trigger bypass exists.
- Full PostgreSQL 16 result: pending GitHub Actions run after this repair is pushed.
- Test count and pass line: pending GitHub Actions run after this repair is pushed.

The first R-1 report claimed green without a PostgreSQL run; that claim was unsupported and incorrect.
