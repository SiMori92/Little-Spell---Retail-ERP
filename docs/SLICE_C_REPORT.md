# Slice C report — reporting

Date: 2026-09-25. Deployment source: `SiMori92/Little-Spell---Retail-ERP`. Dataset remains **SAMPLE**. This slice adds read-only reporting and Addendum D posting corrections. It does not perform a close or certify any gate.

## Contract and implementation

All seven preflight artifacts existed before work. The frozen event catalogue header is v1.3 and includes Addenda A–D. `../contracts/*` and `../state/*` were read only. No schema fixture was marked verified.

Addendum D now routes both signs of `settlement.reversed` rate delta to 6116, keeps the explicit reversal charge in 6181, and credits 6116 for a negative `settlement.received` spread. A named `DJANGO_SETTLEMENT_SPREAD_TOLERANCE_FRACTION` setting escalates excessive absolute spread; its default **0.10 is provisional and awaits Agent 2 approval**. Synthetic tests cover both signs and all 22 Etsy-rail event rules for absence of 7111 (20 postable, two reserved payment rules blocked).

Seven authenticated reports are available at `/reports/`: contribution by order, SKU, and sales channel; P&L; balance sheet account balances; CAC; and inventory roll-forward. They are queries over posted evidence, not stored contribution columns. Each numeric/absent cell carries dataset kind, cost basis, source period, and unit. Missing inputs render `ABSENT` with a reason. Provisional amounts display `PROVISIONAL COST BASIS — NOT ACTUAL`, with `[ESTIMATE]` for an estimated source. Every CSV includes a first provenance row and, in SAMPLE mode, a `SAMPLE_` filename. CSV fields are a report-specific whitelist of codes, counts, and money; customer names and addresses are not exported. HTML retains the SAMPLE banner.

Contribution reads revenue and costs from posted journal entries. Seller discount 4191 reduces gross product plus shipping revenue to avoid overstating contribution; this addition reconciles to the contract's net revenue definition. 6115 is excluded from orders and remains in period P&L. Order-level shipping, discount, fees, conversion, freight, duty, and packaging are allocated to SKUs by gross product revenue share **in the query only**; product COGS uses SKU-tagged journal lines. An incomplete tag set makes SKU contribution and the “which SKU earns most” answer ABSENT. The NT$200 comparison is per order; SKU and channel summaries compare their per-order averages. A reporting cross-check compares period order contributions with posted contribution accounts and labels TIES, MISMATCH, or UNPROVABLE. It is not G-4 enforcement or a close gate.

`JournalLine.sku` now tags SKU inventory and COGS legs needed for that query. `InventoryMove.value_delta_twd` is nullable and sign-checked so a sourced ops movement can be compared independently with SKU-tagged GL inventory. Existing moves have no invented value. The roll-forward needs a posted opening count, a sourced opening move, valued movements, and SKU-tagged ledger value before it can say TIES. It never derives an opening balance from movements. The total checks all inventory GL lines; untagged inventory value makes the identity UNPROVABLE. This is a reporting identity, not G-3 enforcement.

## ABSENT and non-actual figures

| Figure | ABSENT condition / non-actual basis |
|---|---|
| Order product revenue, shipping revenue, seller discount | ABSENT when a dispatched order has no single posted `order.shipped` entry. |
| Order transaction, processing, offsite ads, regulatory fees | ABSENT when `order.fees_assessed` is missing, unposted, or errored. 6115 is never part of this figure. |
| Product COGS and packaging COGS | ABSENT when `order.cogs_relieved` is missing, unposted, or errored. **Provisional** if its source has no actual cost basis; the current sample has no landed cost or opening count and cannot yield actual COGS. |
| Outbound freight | ABSENT without posted accrual/invoice evidence or with an unposted required leg. **Provisional [ESTIMATE]** while only a freight accrual exists. |
| DDP duty | ABSENT when DDP/DDU position is unknown or required duty evidence is missing/unposted. Posted DDU acknowledgement gives a genuine zero. **Provisional [ESTIMATE]** with DDP accrual but no invoice. |
| Conversion 6116 | ABSENT without resolved TWD settlement coverage for that order, including unresolved duplicate order references. The sample's USD settlement cannot serve as Addendum C TWD evidence. |
| Contribution, NT$200 gap, contribution after acquisition | ABSENT if any required component is ABSENT; **provisional** if COGS or another component is provisional. After-acquisition is additionally ABSENT without recorded advertising spend or dispatched-order denominator. |
| SKU contribution, ranking, gap | ABSENT when order components are absent, SKU COGS tags do not exactly cover posted order COGS, or there are no dispatched SKU lines. Any provisional input propagates to the SKU result. The winning SKU is ABSENT if any contender cannot be computed. |
| Sales-channel contribution, average, gap | ABSENT when there are no dispatched orders for the report or when any member order is incomplete. Any provisional member propagates. |
| P&L / balance sheet account line | ABSENT when no posted lines exist. Source entries marked provisional or estimated display their basis; neither statement fabricates missing lines. The balance sheet is cumulative and retains current earnings outside a close. |
| Channel ad spend and CAC | Spend is ABSENT without posted 6141/6142/6143 lines. **All channel CAC denominators and CAC values are ABSENT** until order-level acquisition attribution exists; sales channel is not attribution. Estimated spend is **provisional [ESTIMATE]**. |
| Blended CAC | ABSENT without posted ad spend or a dispatched-order denominator. Estimated spend makes it **provisional [ESTIMATE]**. |
| Inventory opening packs and value | ABSENT without a posted opening count plus sourced opening move/value, or if count and move disagree. The current sample has no opening count. |
| Inventory closing packs / ops value / GL value | Closing is ABSENT without opening; ops value is ABSENT without all sourced movement values; SKU GL value is ABSENT without SKU-tagged inventory lines. Movement quantities with no opening do not prove a close. |
| Inventory identity | **UNPROVABLE** when count, valuation, or SKU GL evidence is absent; MISMATCH when sourced quantity/value disagree. It cannot currently satisfy G-3 on the sample. |

No claim above means an actual commercial figure exists today. The sample lacks verified landed cost, an opening count, and a representative TWD settlement. Channel acquisition attribution is absent. Reporting figures computed from the synthetic test records establish arithmetic and labels only.

## Verification and limits

The synthetic two-SKU order gives NT$173 contribution by hand: 250 product + 50 shipping − 20 seller discount − 15 fees − 2 conversion − 12 freight − 3 DDP duty − 70 product COGS − 5 packaging. Blended CAC is NT$24 and after-acquisition is NT$149. SKU allocations sum back to NT$173; period ledger cross-check ties in that fixture. Adding a 6115 listing fee leaves order contribution unchanged. An extra 6116 ledger line produces a disclosed mismatch. An unposted freight/duty accrual or missing COGS makes contribution ABSENT. Separate synthetic inventory records prove a 5-pack/NT$50 opening less 1 pack/NT$10 movement ties to 4 packs/NT$40 GL, and a NT$1 movement valuation change reports MISMATCH. With no count, the report says UNPROVABLE.

**Fixture coverage:** no report is verified against a founder-approved real schema fixture. Slice A sample import mechanics are covered by their existing tests, but the Slice C money reports are synthetic-only; empty-source report and export behavior is tested independently. Existing SAMPLE records cannot establish actual contribution, G-3, or G-4. The reporting cross-check is sensitive to timing differences between dispatch, invoices, and settlements; mismatches require review and are never silently adjusted. No close, five-gate enforcement, settlement aging, carrier reconciliation, or notifications were built.

Verification on local PostgreSQL: `python manage.py test` passed 115 tests; `makemigrations --check --dry-run` found no model drift; `manage.py check` reported no issues. No test prints customer rows.

**Elapsed build time:** work began 2026-09-25 07:13:12 UTC; implementation, full-suite verification, and staged guard review ended 2026-09-25 07:37:14 UTC. Wall-clock elapsed: **0.40 hours** (24 minutes 2 seconds). This is observed elapsed time, not an estimate of effort.
