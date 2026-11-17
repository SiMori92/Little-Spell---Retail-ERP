# M2 — Selling checkpoint

Date: 2026-11-16 (Asia/Hong_Kong). Founder instruction: “proceed M2”, followed by “pls continue where you left over”. M2 is delivered for review. Stop before M3. This checkpoint is not a replacement for the founder's actual books.

## Delivered

- `/sell` with four-step Enter → Check → Preview → Confirm flows for an Etsy order-items/statement pair, Instagram v2 CSV, manual Instagram deals, evidenced Etsy header review, and Etsy dispatch.
- Shared strict Zod entity/payload/effect schemas, including distinct schemas for each supported ledger-event payload. All effects are recomputed and compared on store replay; input/effect objects are independently cloned.
- Exact ordered Etsy headers, monthly filename provenance, date parsing, exact decimal-string identities, coupon-funder rules with validity/evidence, unique transactions, order-level consistency, gross-before-discount Sale controls, fee/listing attribution, period-boundary/aged-control warnings, and changed-source refusal.
- Statement multiset controls preserve identical-row multiplicity and ignore row ordering. Repeat files, later retries, and economically identical reordered statement pairs create zero additional runs. Existing order facts cannot be overwritten.
- Buyer/contact columns and item descriptions are discarded before persistence. Statement Title and free-form Info narratives are discarded; only required order/listing references remain. The original source CSVs are not retained or attached. Errors do not echo submitted values. Keep original evidence privately outside the ERP.
- Instagram anonymous customer references, line continuity, quote/payment/shipment chronology, next follow-up dates, lost reasons, consent and journey history, unique wallet references, forward-only immutable snapshots, and immutable paid facts. Both table and kanban views open a record drawer with status history.
- TanStack lists for orders, deals, statement periods/rows, queued events, and deal history; search, filters, sorting, record details, and current-view CSV exports. The narrow-screen board scrolls internally, not the whole page.
- Append-only Etsy dispatch date, tracking reference, evidence, and piece deductions derived from each product's sale-unit conversion. Availability is checked across the full dated movement timeline, so neither future stock nor a backdated oversell can pass. Damaged stock and M1 preparation are not availability.
- Separate UNPOSTED placement, revenue-at-dispatch, COGS, fee, listing-cost, and settlement events. Imports never post a journal or invent FX, WAC, zero cost, bank value dates, or bank evidence.
- Pure placement/dispatch posting functions tested for seller/platform discounts, domestic/export revenue accounts, exact functional-TWD balance, and historical deposit FX. They are not exposed as an automatic posting API; M4 retains accounting review and posting.
- Today tasks derived from recorded setup/selling facts: orders to ship, due Instagram follow-ups, and unverified-header review. No financial KPI is invented.
- First start now creates three immutable SAMPLE runs: fixture manifest, master/reference bootstrap, and the authored Instagram pipeline import (12 deals / 13 source lines). It never auto-approves Etsy headers or invents opening stock.

## Evidence gates retained

1. Both copied Etsy header contracts remain `verified:false`. Preview does not change that. A founder may explicitly record their review of the exact current ordered-header fingerprints, with evidence and confirmation, for this dataset only. No review is seeded automatically and the frozen reference is unchanged.
2. Paid/shipped/followed-up ACTUAL Instagram states remain refused until H-0b wallet statement/ledger evidence is implemented. SAMPLE pipeline labels are not proof of cash or inventory movements. Journey history sends no email or notification.
3. ACTUAL USD-to-USD deposits are refused as the known synthetic statement shape. The first real TWD deposit contract and its FX/bank evidence are not invented.
4. Etsy fixture dispatch requires existing counted stock. The browser/domain tests inject explicitly synthetic counted-stock facts into isolated test workspaces; ordinary startup does not. Normal SAMPLE users can explore the pipeline, but booking shipped Etsy fixtures waits for M3 stock support unless a valid counted position already exists.

## Reference differences made explicit

- The reference Etsy importer emits gross as the placement amount even for seller-funded discounts, while its posting function requires the effective rail amount. V2 emits buyer-paid/net for seller-funded placement and gross for platform-funded placement, keeping the gross Sale control separate. This follows the posting rule rather than copying an input that its own posting function refuses. Example: gross USD 30.9700 less seller discount 2.6000 gives a 28.3700 deposit; at public FX 32.0000 the deposit is TWD 907.8400, not 991.0400. Tests prove the dispatch entry balances without a plug.
- Statement identity is computed after privacy normalization of narratives. Duplicate occurrences/order independence are preserved, but hash bytes need not equal Django's narrative-bearing digest. Changing economic rows or duplicate multiplicity still refuses replacement. This is not a claim of bit-identical raw-source evidence; originals remain the founder's separately retained evidence.
- Coupon funding is recorded as evidenced import rules rather than loading or editing an external founder CSV. Zero-discount orders resolve to `none`; discounted orders require exactly one valid seller/platform rule.
- Paid deal facts are frozen more conservatively than the current reference: shipping charge, destination, payment date, and existing line set also cannot change. `lost` and `followed_up` are terminal. Corrections need a separately designed reversing workflow, not an update disguised as a forward state.
- Etsy piece consumption is an immutable `selling.shipment` operational effect, not a fabricated zero-valued `stock.moved`. M3/M4 must integrate its deductions and append valuations without deducting the same shipment twice. General InventoryMove/WAC parity remains deferred.
- Instagram shipped states remain pipeline snapshots as in the reference importer, not warehouse dispatches or accounting entries. Real wallet/stock/accounting integration remains dependent on the missing wallet contract.

## Observed checks

| Check | Result |
|---|---|
| Runtime | Node 22.23.5, pnpm 10.20.0; no dependency additions |
| Typecheck | PASS; strict full-project check |
| Lint and money guard | PASS; zero errors, three existing warnings |
| Vitest | PASS; 65 tests across 10 files |
| Playwright Chromium | PASS; 13 tests, including all M0/M1 flows |
| Production build | PASS; four dynamic-filesystem tracing warnings |
| Production startup | PASS on loopback; three SAMPLE runs and 12 pipeline deals; headers remain unverified |
| Production preview | PASS; zero additional runs |
| Production mobile board | PASS at a 390-pixel viewport |
| Production tamper/startup | PASS in a copied synthetic workspace; broken hash yields read-only, names the bad run, disables recording; no repair attempted |
| Source/PII guard | All nonignored authored files are scanned directly, including untracked source; final inventory/audit saved locally |
| Frozen reference comparison | The 134 snapshotted app/contract files retain their original SHA256 and mtime |

Vitest covers the unverified-header gate, atomic pair import, exact controls, zero-write duplicates, reordered statement idempotency, duplicate multiplicity changes, malformed headers, missing coupon evidence, provenance, discarded buyer fields, insufficient/future stock, unshipped/dispatch event separation, version/head conflicts, paid-field immutability, ACTUAL wallet refusal, unique wallet references, final-state refusal, effective closed periods, effect forgery, and recomputed-hash tampering. The earlier crash/lock/recovery/money-guard tests remain green.

Playwright exercises explicit header review, blocked preview confirmation, the Etsy pair happy path, duplicate imports, statement/accounting drawers, inline deal validation, forward status/history, table/kanban navigation, derived Today guidance, guided dispatch with a zero-write preview, the already-seeded Instagram file's zero-run re-import, and mobile containment.

Warnings were not hidden: one existing anonymous PostCSS export and two TanStack/React-Compiler compatibility notices remain. Next's filesystem tracing warnings are unchanged; builds stay local and private. Final QA logs and synthetic workspaces are under ignored `.tools/` and `test-results/`.

## Parity and remaining work

- Seventeen reference rows become BUILT: Etsy module/schema/coupon/import replacements, IG intake, two importer command replacements, seven selling models, and three current header contracts. The obsolete IG v1 pack header is DROPPED with a reason. Mixed intake/posting modules remain DEFERRED for their unbuilt portions; `PARITY.md` records the exact boundaries.
- Revenue timing is implemented at the event boundary and in tested pure posting functions. There is no posted revenue balance in M2. Full FX masters, accounting review/posting, catalogue worked examples, COGS valuation, sales cancellations/refunds/reversals, and report parity remain M3/M4. No misleading generic Undo is exposed for a selling run.
- Financial dashboards, computed G-1…G-5, founder-authorized month close, complete SAMPLE accounting materialization, and the independent four-decimal report tie-out remain M5/final gates. `PARITY_TIEOUT.md` remains NOT RUN.
- The ACTUAL-environment discrepancy noted in M1 still requires a founder decision before activation. No activation endpoint was added.
- No commits, branches, root decision edits, external backups, or customer notifications were made. The direct source scan is meaningful; the still-empty git index does not substitute for the first-commit/fresh-clone gate. A true fresh clone on the founder's machine and the orchestrator's full root-wide mtime check remain outstanding.
- All authored changes are inside `erp/`. The 134-file reference comparison is narrower than a full-root mtime audit. Real customer/inbox files were not opened.

See `FILES_WRITTEN.md` for the complete authored-file inventory. Founder review is required before dispatching M3.
