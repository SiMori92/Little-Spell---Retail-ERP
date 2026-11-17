# Financial parity — scoped PASS; full RB gate BLOCKED

Recomputed 2026-11-17. The G3 purchasing fixtures plus an identical complete zero opening and four explicit synthetic manual vouchers tie independently to the frozen reference at NT$0.0001. This is a scoped numerical result. **Full identical-fixture Etsy/all-source parity is not certified.**

## Independent comparison

Both runners load the G3 supplier/product snapshots, zero opening on 2026-01-01, PO-2026-002, deposit, both receipt/invoice pairs and both balance payments. Both additionally post the same explicit SAMPLE vouchers on 2026-10-02: owner capital 200000.0000; software accrual 1234.5678; tax assessment 1250.0000; tax payment 1000.0000. This exercises nonzero P&L, account balances and inventory rather than comparing empty reports.

| Output | Result |
|---|---|
| Trial balance — all sourced account debit/credit totals | Exact, zero differences |
| P&L — software 1234.5678 and tax 1250.0000 | Exact, zero differences |
| Balance-sheet account balances | Exact, zero differences |
| Inventory — 3000 MT pieces / 60900.0000 and 7500 FS pieces / 74550.0000 | Exact, zero differences |
| Second import of all G3 purchasing files | Zero new runs |

Saved evidence:

- `PARITY_REFERENCE_G3.json`: frozen Django posting/reporting output.
- `PARITY_V2_G3.json`: v2 store/projection output.
- `PARITY_DIFF_G3.json`: independent numeric comparison; `differences: []`, `secondImportNewRuns: 0`.

Reproduce from `erp/` in the original reference workspace:

```sh
PYTHONDONTWRITEBYTECODE=1 ../app/.venv/bin/python scripts/reference-tieout.py
node --import tsx --conditions=react-server scripts/parity-tieout.ts
```

The Python harness imports unmodified reference modules without project settings or `.env`, uses an in-memory validation adapter, disables bytecode writes, and omits PostgreSQL-specific audit receivers through a generic core AppConfig. It runs the real reference purchasing importers, posting functions and report builders. It does not test PostgreSQL triggers/grants. This verification harness depends on the frozen reference at test time; the ERP runtime does not.

## Full Etsy comparison — blocked, not zero

`PARITY_REFERENCE_ETSY_BLOCKERS.json` reproduces the importer's placement envelope through the unmodified reference `placed()` function. The source importer passes gross minor units; posting requires gross less seller-funded discount. These three SAMPLE orders are refused:

| Synthetic order | Imported USD minor | Required USD minor |
|---|---|---|
| 2918473019 | 3097 | 2837 |
| 2918473035 | 1749 | 1569 |
| 2918473062 | 4447 | 3897 |

The reference error is “rail amount contradicts discount funder; refuse both readings”. Its importer/posting discrepancy must be resolved through an authorized source/contract decision. v2 follows the already frozen seller-deposit rule; it does not adopt a knowingly conflicting gross deposit to manufacture parity. No reference file was changed. The probe is not a claim that the complete Etsy importer/poster/report pipeline passed.

The supplied USD Deposit also lacks real TWD bank-credit/value-date and cleared-item composition evidence. Settlement remains UNPOSTED, contribution stays ABSENT where settlement inputs are missing, and G-2 remains NOT_RUNNABLE. Addendum J remains held under the current catalogue. No real month has closed in v2.

## Remaining release checks

The all-fixture trial balance/P&L/inventory comparison, full report Figure/section/export parity, source-backed settlement and operational-correction flows, successful financial-close happy path, founder-machine fresh clone, first-commit ordering, and full-root orchestrator mtime audit remain unpassed. The 119 tests, 22 browser flows and production smoke are software evidence; they do not waive those gates. Keep the frozen reference until the founder has completed a real month with all five checks green.
