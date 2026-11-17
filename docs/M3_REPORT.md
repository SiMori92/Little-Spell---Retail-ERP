# M3 — Buying and stock checkpoint

Date: 2026-11-17 (Asia/Hong_Kong). Founder instruction: “proceed to M3”, followed by “continue where you left over”. M3 is delivered for review with the boundaries below. Stop before M4. This checkpoint does not certify readiness to replace the actual books.

## Delivered

- `/buy`: four-step entry/CSV → check → preview → confirm flows for purchase orders, forward statuses, goods receipts, supplier invoices, and deposit/balance/refund/forfeiture payments. Lists expose unmatched documents, discrepancies, lifecycle history, landed allocations, search, filters, sorting, and current-view exports.
- `/stock`: complete physical opening/adjustment counts, explicit founder confirmation, stock positions, movement/count history, exact dated WAC, and pending shipment COGS. Unknown positions say “Not counted” rather than displaying an evidenced zero. Damaged opening pieces are zero-value memos.
- Shared strict Zod schemas, current CSV headers, deterministic natural-key records, replay recomputation, optimistic preview-head checks, loopback/same-origin API protection, immutable runs, and zero-write retries. No booked update/delete route was added.
- Draft PO changes append versions. Sent commercial commitments freeze supplier, quote, line set, quantities, and prices. Sending checks compliance. Partial deliveries require a short-close reason; each PO line has one delivery and invoice, matching the reference boundary.
- Receipt-first and invoice-first both work. An unmatched document creates neither stock nor payable. Once quantities and evidence match, one atomic run posts the balanced receipt journal and corresponding stock effects. Confirmed supplier payments and counts also post their scoped journals, matching the reference's automatic posting behavior; the full accounting review/posting engine remains M4.
- Freight and noncreditable tax allocate by line value with the remainder on the highest line number. Damage splits from the full landed amount, with the exact remaining value assigned to good stock. Optional stated line tax must cover all lines and tie to invoice tax. Creditable tax requires a GUI number and an explicitly eligible business tax regime, rechecked at matching.
- Deposits are capped at the commitment excluding tax and blocked after a receipt. Balances require a posted match and cannot overpay. Cancelled deposits can be refunded or forfeited only within the remaining balance. Payments use the reference TWD bank account restriction. Pro-rata deposit application uses the exact completion remainder; supplier-stated differences stay visible rather than becoming a plug.
- Complete stock counts include every active SKU, including zero rows. Opening precedes stock activity; later decreases consume exact current WAC, and unexplained increases refuse. Count checkpoints protect against later backdated shipments and changes to an already booked adjustment's valuation.
- M2 dispatch quantities are consumed once in the dated inventory projection. Their cost is visibly pending, UNPOSTED COGS. M4 must append accounting valuation without deducting those quantities again.
- Today now includes supplier deliveries due, unmatched purchasing documents, and invoice balances. Setup's opening checklist links to the actual stock-count flow. An M1 preparation or no-stock declaration alone no longer completes that item; it does not book inventory.

## Compatibility and QA fixes

The frozen 74-account snapshot omits account 1266. The exact approved supplier-prepayment account was found in the reference migration and copied to `seed/coa_addenda.json`. The original bootstrap still emits its original 74 accounts, preserving existing run bytes and replay behavior. The first purchasing run appends adoption of account 1266; the resulting approved chart has 75 accounts. No historical run is rewritten.

Browser validation exposed a Decimal exception on invalid blank numeric fields. Aborting numeric-format validation now produces inline Zod issues before decimal refinements execute. A regression test covers the failure; valid stored payloads are unchanged.

Production QA initially assumed the downloaded SAMPLE opening schedule contained only zero rows. It actually contains 10 good pieces at NT$10 and two damaged memo pieces. The application booked NT$100 correctly. The download label was corrected to “complete SAMPLE opening-count schedule”, and the smoke test was rerun in a fresh isolated workspace.

## Observed validation

| Check | Result |
|---|---|
| Runtime | Node 22.23.5, pnpm 10.20.0; no dependency additions |
| Typecheck | PASS, full strict project |
| Lint and money guard | PASS; zero errors, three existing warnings |
| Vitest | PASS; 91 tests across 12 files, including 20 killed-write attempts |
| Playwright Chromium | PASS; 18 tests, including all M0–M2 flows and five M3 flows |
| Production build | PASS; four existing dynamic-filesystem tracing warnings |
| Isolated production startup | PASS; three SAMPLE runs, stock initially unknown |
| Guided opening upload/preview/confirmation | PASS; preview writes zero, good stock NT$100, damaged memo adds no sellable stock |
| Receipt/invoice production API | PASS; unmatched payable zero, matched payable 143850.0000, damage 388.5000 |
| Repeat invoice | PASS; zero extra runs |
| Packaging separation | PASS; packaging receipt values do not enter sellable WAC |
| Mobile Buy/Stock | PASS at 390-pixel viewport |
| Production tamper restart | PASS in copied synthetic data; read-only, first bad run named, recording disabled; no repair |
| Historical chart bootstrap | PASS; unchanged old bootstrap, additive account adoption |

The final unit, browser, lint, and typecheck runs include the Setup checklist change. The final build includes it too. The broader production smoke preceded that last checklist-only change. Warnings were not suppressed: one PostCSS anonymous export and two TanStack compiler compatibility notices remain; the four Next filesystem tracing warnings remain.

Tests cover exact allocation, full two-receipt deposit settlement, both matching orders, all G3 fixture re-imports, mismatches, sent commitments, compliance, short-close, tax eligibility, unsupported inputs, overpayment, cancelled deposits, complete counts, exact WAC-to-zero, damage, backdating, closed effective dates, forged effects, rehashed tampering, stale previews, and cross-origin refusal. The G3 fixtures use their own master scenario and are not silently mixed with the startup masters.

## Parity and remaining gates

`PARITY.md` resolves 31 existing rows to BUILT and adds three identified receiving/payment importer rows with their replacements. The obsolete count-v1 pack contract is DROPPED with a reason. Mixed inventory/WAC/posting rows remain explicitly partial or DEFERRED; this is scoped implementation, not a claim of full module parity.

- Packaging count rows must currently be explicit zero. Nonzero packaging counts require a dedicated accounting policy; packaging receipt value is already supported separately.
- Carrier/duty columns, goods-in-transit receipt processing, multiple deliveries/invoices per PO line, late-cost corrections, returns, general writeoffs, and guided general reversals remain unavailable. Unsupported writes refuse; they are not silently estimated or edited. A booked correction needs a future reversing workflow.
- Supplier-stated deposit discrepancies are surfaced. A deposit cannot overapply an invoice or be backdated into a receipt that predates its payment; unsupported matching stays unposted rather than inventing a balancing amount.
- Selling/manual accounting, FX, final COGS posting, trial balance/P&L/balance sheet, and full catalogue coverage remain M4. Computed close gates, authorization, dashboard completion, and full independent financial tie-out remain M5/final gates.
- `PARITY_TIEOUT.md` remains **NOT RUN**. No reference financial outputs or zero differences are claimed. The reference Django application was not executed or modified.
- No ACTUAL activation endpoint was introduced. The previously documented ACTUAL-environment discrepancy remains unresolved before activation.
- Direct source scanning includes untracked files. The git index is still empty; no commit or branch was created. First-commit ordering and a true fresh-clone run on the founder's machine remain final gate work.
- The 134-file frozen-reference SHA256/mtime comparison is narrower than the orchestrator's full-root mtime audit. All authored changes are inside `erp/`; real customer/inbox files were not opened. No notifications, deployment, root decision edits, or external backup writes were made.

See `FILES_WRITTEN.md` for the complete current authored-file inventory. QA logs, synthetic runtime workspaces, and the final source/reference audit are ignored under `.tools/`.
