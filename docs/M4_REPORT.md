# M4 — Money and accounting checkpoint

Date: 2026-11-17, Asia/Hong_Kong. Authorized together with M5 and a subsequent smoke test. All authored work remains inside `erp/`.

## Delivered

- `/money` provides four-step guided forms for expense receipts, six manual entry types, evidenced public FX, freight accruals/invoices, duty positions/invoices, clearing explanations, journal corrections, and inventory attribution. Shared Zod schemas validate forms, requests, effects and replay. Manual facts and receipts save **UNPOSTED**; review/post is a separate action.
- Manual accrual estimates carry their stated basis. Reversing an accrual names its posted original and cannot be duplicated. Inventory revaluation is refused. Owner investment/withdrawal/loan use equity/drawings/liability respectively. Tax assessments retain the professional-confirmation flag and voucher reference.
- Receipt CSV intake uses the current header, supported optional columns, dated dataset filename, cents precision, unique evidence and atomic fact creation. Re-importing the same file writes no new run. Changed evidence refuses. Cash/bank routing is currently limited to petty cash and the operating bank.
- Public Bank of Taiwan rate evidence is immutable by date/currency and supports six decimals. Etsy deposits use the order-date rate; fee components use the fee-row-date public rate under CR-A.4. Dispatch releases the original held deposit into the appropriate revenue/shipping/discount accounts. Dispatch cannot post before placement.
- COGS posts the exact M3 dated WAC consumption, with SKU and journal quantity attribution, without another inventory deduction. Posted costs are shown as POSTED in Stock; pending COGS excludes them. Backdated activity that would change an already posted cost refuses. Repeated-SKU order lines aggregate for cost verification and gross-share allocation.
- Older M3 journals retain their exact bytes. An explicit reviewed attribution action appends SKU/piece metadata calculated from their original receipt/count facts. Reports apply that metadata without changing run files. Independent journal quantity/value are compared against operational stock in G-3.
- Eligible accounting journals can be corrected through a previewed opposite entry; the original remains posted and visible. Operational inventory/document journals cannot be “undone” by reversing only their money. No update/delete endpoint was introduced.
- Trial balance, P&L, balance-sheet account balances, order/SKU/channel contribution, CAC, inventory roll-forward, signed clearing FIFO aging, carrier reconciliation and purchasing/Instagram reports are available through the shared report projections. Missing inputs remain ABSENT. Estimated/provisional costs retain labels; no blended or channel CAC is invented from missing acquisition evidence.
- Supplementary pure functions cover cancellations, refunds with original fee credits, freight/duty variances, reprints, transit, late cost allocation and D.1 settlement/reversal economics. Numeric tests assert the specified account sides and amounts, including negative conversion spread. RESERVED gateway operations explicitly refuse. Pure-function coverage does **not** mean the missing operational emitters below are available.

## Verification

The final whole-project suite passed 119 Vitest tests across 14 files and 22 Playwright flows. The strengthened accounting subset passed 28 tests with explicit expected account/amount assertions. Strict typecheck, money guard, lint and production build passed. Lint retains the three pre-existing warnings; Next retains four dynamic-filesystem tracing warnings. No new dependency was added.

The production smoke test passed guided unposted funding, separate posting, zero-write preview, zero-write duplicate, guided reversing journal, guided expense, report pages, mobile containment, checksummed backup/restore and tamper read-only behavior with no page errors. See `SMOKE_REPORT.md`.

## Parity findings and boundaries

An independent run of frozen Django posting/reporting code on the G3 fixtures and the same complete zero opening ties to v2's trial balance, P&L, balance-sheet balances and inventory at four decimals. A second G3 import writes zero runs. Independent outputs and the machine-readable diff are saved beside `PARITY_TIEOUT.md`.

The full Etsy comparison is blocked by a reproducible frozen-reference inconsistency: the importer supplies gross amounts to `order.placed`, while its posting function requires seller-funded discounted receipts. Three SAMPLE orders fail that reference posting rule. The report records the imported and required amounts; neither the frozen app nor the v2 deposit rule was changed to conceal the discrepancy.

The current Etsy Deposit source also lacks proven TWD bank credit, value-date and cleared-item composition. v2 refuses posting it. Addendum J remains held as specified by the current catalogue; neither a public-rate carrying set nor an applied settlement rate is guessed. This prevents a genuine all-green close on the supplied SAMPLE sources.

General operational refund/cancellation/reprint flows, returns/writeoffs, supplier-document reversals, transit receipt matching, late-cost propagation and nonzero packaging counts remain DEFERRED. Their available pure posting functions do not substitute for those source-backed workflows. Packaging receipts still remain outside sellable WAC, and packaging ops-to-GL identity may remain NOT_RUNNABLE. Complete reference Figure unit/section/export parity and all historical worked examples are not certified. These boundaries remain explicit in `PARITY.md`.

This checkpoint is reviewable implementation, **not** a passed final RB release gate or approval to abandon the reference books.
