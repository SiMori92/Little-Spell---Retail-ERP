# Slice D report — reconciliation and close

Date: 2026-09-25. Source repository: `SiMori92/Little-Spell---Retail-ERP`. The application remains **SAMPLE**. All six required preflight artifacts existed; `event_catalogue_FROZEN.md` starts at v1.3 and includes Addenda A–D. `../contracts/*` and `../state/*` were read only. The bundled CoA snapshot hash matches the current `../state/coa.csv` SHA-256 (`c282a2bc5b7d24fd0b0b8c11fe854ec1d619c7501ae4e34de09ac3fa02de4a20`). No schema fixture was marked verified.

## What was built

`acct.gates` runs G-1 through G-5 as executable checks. G-1 counts **both** entire event streams through period end, with either a null posting link or a non-null posting error treated as unposted; it has no scope exemption. G-2 ages FIFO open 1191/1192/1193 items and lists 2205 open items, then requires both an explained age of at most 15 business days and an **exact** zero 2205 balance. If no posted TWD settlement source exists, it returns `NOT_RUNNABLE`, which stops close. Business days count Monday–Friday; no Taiwan public-holiday calendar has been supplied. This is conservative for aging (it may flag an item early), and that calendar remains open before a live close.

G-3 independently compares signed ops movement quantity and value per SKU against SKU-tagged inventory journal quantity and value in 1231/1232/1233. It requires a posted opening count and sourced opening move. New journal lines record SKU quantity; existing lines without it cannot be treated as proven. An untagged inventory line, missing move valuation, or missing opening count returns `NOT_RUNNABLE`. G-4 compares dispatched-order contribution with the posted period P&L contribution accounts, then independently recomputes gross-revenue-share SKU allocations and checks their totals. No journal allocation is written. G-5 checks the frozen chart and loaded accounts for suspense, rounding and difference accounts; checks suspicious journal-line memos for a line source reference; and requires `[ESTIMATE]` plus a stated memo basis on estimated entries and any carrier accrual still open at period end. Posting now carries source references and estimate basis into new journal lines.

The authenticated `/reports/settlement-aging/` report lists every open rail item, its weekday age, named cause or absence, and a signed total. `/reports/carrier-reconciliation/` compares 6131 accrual, 2172 invoiced amount, and remaining 2191 per order and in period totals. An uninvoiced accrual displays `[ESTIMATE]` and its basis or states the missing basis that makes G-5 fail. Both reports have SAMPLE-marked CSV exports with provenance and no customer fields. `record_clearing_cause` adds a named cause and evidence reference without changing the journal.

`close_period gate1 YYYY-MM --actor ... --evidence-ref ...` records the WD+1 input-review signoff **only before any journal entry in that period**. It records external pre-close evidence; it does not claim to automate P-1 through P-33. `close_period close ...` becomes due at WD+3, times the attempt, and runs G-1 → G-5 in order, stopping on the first `FAIL` or `NOT_RUNNABLE`. A successful run locks both accounting and ops periods; a blocked run leaves both open and produces no close statement. Each attempt stores period, runner, gate results/reasons, remaining work, timestamps, elapsed seconds, and a SHA-256 HMAC signature. Close-run and audit rows reject UPDATE/DELETE at the database. `close_period reopen ... --actor ... --reason ...` reopens both locks in one transaction and writes an audit row.

## Current-data results

The local SAMPLE database used for this run contains **0 orders, 0 ops events, 0 inventory moves, and 0 journal entries**. Read-only G-1…G-5 diagnostics were run for **2025-12**. These are current local-data results, not real-business or founder-approved fixture results.

| Gate | Local result | Reason |
|---|---|---|
| G-1 | PASS on empty streams | Zero unposted/errored ops and manual rows. This is a mechanical empty-data pass, not evidence of a completed import. |
| G-2 | **NOT RUNNABLE → close FAIL** | Q-1 remains OPEN: there is no posted TWD `settlement.received` source, so rail aging cannot be certified. No waiver or tolerance was applied. |
| G-3 | **NOT RUNNABLE → close FAIL** | No posted opening inventory count or valued movement. No opening balance was derived and no adjustment was posted. |
| G-4 | **NOT RUNNABLE → close FAIL** | No dispatched orders or contribution evidence to tie to P&L. |
| G-5 | PASS on current chart/empty journal | No prohibited account in the matching CoA snapshot or loaded chart and no journal line to inspect. This does not certify future estimates. |

**Measured close attempt:** local `CloseRun` 1, period 2025-12, runner `codex-slice-d-diagnostic`, elapsed **0.0096 seconds**. It is **BLOCKED** at Gate 1 because no WD+1 pre-close input-review signoff exists; G-1…G-5 were not run inside that attempt. Its signature verifies and the period remains OPEN. The diagnostics above were separate, read-only evaluations of all five gates. No successful close occurred, so the Phase 2 requirement of **one clean close under one hour is not met**. A short blocked attempt cannot satisfy that requirement.

## Positive and negative tests

All gate positives below use synthetic, non-customer records. No golden or real schema fixture is claimed verified.

| Check | Injected case | Outcome |
|---|---|---|
| G-1 | Empty streams | PASS. |
| G-1 | Ops event with null posting link | FAIL. |
| G-1 | Ops event with posting link but unresolved `posting_error` | FAIL. |
| G-1 | Manual event with null posting link | FAIL. |
| G-1 | Manual event with posting link but unresolved `posting_error` | FAIL. |
| G-2 | Posted settlement source, aged item with named evidenced cause, 2205 zero | PASS. |
| G-2 | No settlement source | NOT RUNNABLE; close treats it as failure. |
| G-2 | Open 1191 item aged **16 business days** with no named cause | FAIL. |
| G-2 | **NT$1** left in 2205 | FAIL at zero tolerance. |
| G-3 | Opening + receipt − sale, signed quantity and value matching GL | PASS. |
| G-3 | Change one ops movement quantity without changing its journal line | FAIL on quantity. |
| G-3 | Change the received lot's ops landed value by NT$1 without `po.landed_cost_adjusted` | FAIL on value while quantity still ties. The ops schema has no separate lot table; this injects the fault into the sourced receipt movement valuation. |
| G-3 | Remove posted opening-count link | NOT RUNNABLE. |
| G-4 | Hand-computed synthetic two-SKU contribution and gross-share allocation | PASS. |
| G-4 | Allocate a header component by unit count instead of gross revenue share | FAIL. |
| G-4 | Add a header fee a second time to SKU reporting without a second ledger charge | FAIL. |
| G-5 | Frozen chart and clean synthetic journal | PASS. |
| G-5 | Add account named `Suspense` | FAIL. |
| G-5 | Add a rounding/difference account | FAIL. |
| G-5 | Journal line memo `adjustment to balance` with null line `source_ref` | FAIL. |
| G-5 | `[ESTIMATE]` line without a stated memo basis | FAIL. |
| G-5 | Open freight accrual without a stated basis | FAIL. |
| Close | G-1 failure | Stops at G-1 and leaves period OPEN. |
| Close | G-2 NOT RUNNABLE | Stops at G-2 and leaves period OPEN. |
| Close/reopen | Synthetic passing gate results, then one-step reopen | Both periods lock, then reopen with an audit record. |

The two reconciliation exports require login and carry `SAMPLE_` filenames and in-file provenance. A carrier accrual test shows `[ESTIMATE]` with basis; a matched invoice clears 2191 and reports zero variance. The close record signature and append-only database protection are tested.

## Limits that remain

- The local database is empty; no live settlement source, opening count, receipt valuation, or dispatched order has been demonstrated. G-2/G-3/G-4 cannot be certified on it.
- Gate 1 records an external P-suite evidence reference but does not implement P-1…P-33. No such signoff was recorded for the measured attempt.
- The weekday clock does not exclude Taiwan public holidays. A sourced holiday calendar is needed before treating a 15-business-day boundary as live-operationally exact.
- Historical journal lines without the new quantity/source metadata remain unprovable where G-3 or G-5 needs that metadata; the migration does not backfill guessed values.
- The frozen rule says `inventory.opening_counted` fires once per dataset, while its current posting payload carries one SKU. A real multi-SKU opening schedule cannot be fully posted through that rule as written. This needs an Agent 2/orchestrator payload ruling before G-3 can certify a multi-SKU live close; the one-SKU synthetic positive test does not resolve it.
- This slice produces no tax pack, notifications, ops console, or customer-facing feature. A close that fails does not publish a signed statement package.

Verification: local PostgreSQL `python manage.py test` passed **137 tests**; `makemigrations --check --dry-run` found no model drift; `manage.py check` found no system issues. No test prints a customer row.
