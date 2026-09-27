# Slice H-0a report — Instagram deals

## Gate and scope

Pre-flight completed against every required file. The frozen catalogue header read:

> # `ledger_event` CATALOGUE — FROZEN v1.5

This slice remains in SAMPLE mode. It creates no `Order`, `LedgerEvent`, `JournalLine`, wallet
statement, posting, writable form, or outbound message. Customers exist only as opaque `C-` codes.

The local PostgreSQL server was unavailable, so the complete PostgreSQL gate ran in GitHub Actions.
CI run **36294225601** passed in **1m 2s** on commit `bb857e0`. The earlier implementation gate,
run **36294121393**, also passed before the final database-trigger hardening.

Migration: `ops/migrations/0009_igdealstatus_igdeal.py`.

## Column contract as built

The authored and verified manifest uses `schemas/ig_deals_header_v1.json`. It accepts only
`inbox/instagram/ig_deals_YYYY-MM.csv` in ACTUAL mode or
`SAMPLE_ig_deals_YYYY-MM.csv` in SAMPLE mode, with this exact ordered header:

| Column | Contract |
|---|---|
| `deal_id` | Required; `IG-YYYYMM-NNN`; its month and `enquiry_at` month must match the filename month. |
| `line_no` | Required whole number at least 1; contiguous from 1 within each deal. |
| `customer_ref` | Required opaque code matching `C-` plus at least four digits. |
| `status` | `enquiry`, `quoted`, `paid`, `shipped`, `followed_up`, or `lost`. |
| `enquiry_at` | Required ISO date on every row. |
| `quoted_at` | ISO date required from quoted onward. |
| `quote_twd` | Four-decimal positive amount required from quoted onward. |
| `follow_up_on` | ISO date required while enquiry or quoted. |
| `lost_reason` | Required only for lost; `no_reply`, `price`, `shipping_cost`, `out_of_stock`, or `other`. |
| `sku` | Required from paid onward and must exist in `Product`. |
| `qty_packs` | Required positive whole number from paid onward. |
| `unit_price_twd` | Required positive amount from paid onward. |
| `shipping_charged_twd` | Required from paid onward; zero is accepted. |
| `ship_country` | Required ISO alpha-2 code from paid onward. |
| `paid_at` | Required ISO date from paid onward. |
| `wallet_txn_id` | Required from paid onward and unique across deal IDs. Numeric values are allowed. |
| `ship_date` | Required ISO date from shipped onward. |
| `consent_marketing` | `yes`, `no`, or blank. |
| `journey_sent` | Required; `none`, `d0`, `d10`, or `d30`. |
| `evidence_ref` | Required and non-blank; phone-shaped content is refused. |

All deal-level fields must agree across a multiline deal. The sample has 12 distinct deals and 13
lines, including one two-line deal, all six statuses, two repeat customers, two lost reasons, overdue
work, and all three consent states. `docs/ig_deals_TEMPLATE.csv` contains the header only.

## Refusals and messages

Every field passes through `ops.pii.refuse_pii`. Refusals name the failed boundary without echoing
sensitive input:

- Email or handle in any column: `PII detected in <column>`.
- Phone-shaped `evidence_ref`: `phone-shaped value detected in evidence_ref`.
- Backward transition or any move out of lost:
  `deal <deal_id> status cannot move backward from <old> to <new>`.
- Changed protected field after paid: `deal <deal_id> <field> cannot change once status >= paid`.
  The protected fields are `quote_twd`, `sku`, `qty_packs`, `unit_price_twd`, and `wallet_txn_id`.
- Open row without a date: `deal <deal_id>: an open deal with no next action`.
- Wallet reused by another deal:
  `wallet_txn_id is used by two different deal_ids: <wallet_txn_id>`.
- Etsy collision:
  `customer_ref appears on an Etsy order; C- codes are Instagram-only: <customer_ref>`.
- Repeated file key: `Instagram file repeats a (deal_id, line_no)`.
- Non-contiguous lines: `deal <deal_id> has line_no gaps`.
- ACTUAL paid-or-later row:
  `paid Instagram deals cannot be committed as ACTUAL until H-0b (wallet statement + ledger) is built — a paid deal with no payment evidence is cash nobody can prove`.

The intake also names malformed IDs, dates, amounts, status-dependent missing fields, unknown SKUs,
conflicting multiline values, omitted stored lines, invalid consent/journey values, and filename-month
mismatches.

## Forward-only status enforcement

`IgDeal` is the current snapshot keyed by dataset, deal ID, and line number. `IgDealStatus` is one
append-only milestone row per dataset, deal, and status.

Enforcement has four layers:

1. The importer locks dataset settings and existing deal rows with `SELECT FOR UPDATE`, rejects
   same-status mutations and backward transitions, and permits snapshot changes only with a forward
   status move.
2. Inside one database transaction it inserts the new `IgDealStatus` first and then updates every
   current-state line. Any failure rolls the history and snapshots back together. Identical re-imports
   perform no writes.
3. PostgreSQL trigger `ops_igdeal_forward_only` rejects same-status or backward direct updates,
   requires the matching new history row, and independently protects paid fields.
4. PostgreSQL trigger `ops_igdealstatus_append_only` rejects every update or delete of history;
   the model and read-only admin refuse those operations as well.

Thus every accepted current-state update is forward, atomic, and explained by exactly one immutable
deal-level history row, including a multiline deal.

## Reports and worked sample examples

Both reports retain the standard SAMPLE banner and provenance-aware CSV behavior. SAMPLE downloads
use a `SAMPLE_` filename and CSV row 1 includes `dataset_kind`, overall `cost_basis`, and
`generated_at`.

### `ig-pipeline?as_of=YYYY-MM-DD`

1. **Follow-ups due.** At 2026-11-15, `IG-202610-001` is open, due 2026-10-05, and 41 days overdue.
   Its quote displays ABSENT because the deal has not reached quoted status. The sample has three
   due follow-ups, ordered oldest first.
2. **Journey due.** `IG-202610-004` shipped 2026-10-20 with consent `yes` and `d0` already sent, so
   `d10` was due 2026-10-30 and is 16 days overdue at the same as-of date. The consent-blank
   multiline customer never appears. Corrected sample deal `IG-202610-005` shipped 2026-10-08
   with `d10` already sent, so `d30` is due 2026-11-07 and is 8 days overdue. The sample has two
   due journey steps.
3. **Conversion by enquiry month.** October 2026 has 12 enquiries, 10 reaching quoted, 6 reaching
   paid, one `no_reply` loss, and one `price` loss. The quoted rate is 83.3333% and paid rate is
   50.0000%. November has zero enquiries, so both rates are ABSENT rather than zero or division by
   zero. Milestone dates, not final status alone, preserve quoted conversion for later lost deals.

### `repeat-rate?period=YYYY-MM`

For the October 2026 first-paid cohort, four Instagram customers reached paid and two have at least
two distinct paid deals, producing 50.0000%. The title and note explicitly say **Instagram only**;
Etsy still has no customer reference. A zero-customer cohort displays an ABSENT rate.

## What H-0b must add

H-0b must add the wallet statement intake and verified payment/refund evidence, then permit ACTUAL
paid deals only through that evidence boundary. It must implement `payment.received` and
`payment.refunded`, the required `1193` accounting changes, and the defined conversion from a paid
Instagram deal to an order/posting path. H-0a deliberately does none of those things.

## Verification and elapsed time

- PostgreSQL migration, deployment checks, complete Django suite, and repository privacy guards:
  PASS in CI run `36294225601`.
- Local non-database checks: Django system check PASS; migration state has no ungenerated changes;
  Python compilation PASS; repository guard unit suite 11/11 PASS.
- H-0a tests cover identical import, exact one-row advancement history, database-level unexplained
  update refusal, every mandated refusal, all three PII cases, report arithmetic, consent exclusion,
  CSV provenance, and zero posting/order creation from H-0a paths.

Elapsed time was **0.45 active engineering hours**. Wall-clock elapsed was approximately **3.0
hours**, including an approximately 2.5-hour pause between the PostgreSQL gate and the requested
continuation/report handoff.

## H-0a.1 — chronological order

H-0a.1 closes the PostgreSQL gate finding that milestone and follow-up dates could be accepted out
of order.

- The intake now compares the present milestone dates in the declared sequence
  `enquiry_at <= quoted_at <= paid_at <= ship_date`. Blank dates are skipped, so two present dates
  cannot evade comparison because a middle date is absent. A present `follow_up_on` must also be on
  or after `enquiry_at`.
- A refusal names the deal, later field and date, and earlier field and date, for example:
  `deal IG-202610-150: ship_date 2026-10-02 is before paid_at 2026-10-03`.
- Migration `ops/migrations/0010_igdeal_date_order.py` adds PostgreSQL CHECK constraint
  `ops_igdeal_date_order`. NULLs pass, while every pair of present milestone dates and the
  enquiry/follow-up pair must be ordered.
- Sample deal `IG-202610-005` now has `ship_date` 2026-10-08. Its next `d30` journey step is due
  2026-11-07 and is 8 days overdue at 2026-11-15; the earlier impossible 2026-10-01 ship date and
  derived 15-day figure are gone.
- Tests independently break enquiry/quoted, quoted/paid, paid/shipped, and enquiry/follow-up order
  and assert that both field names appear in each refusal. A forward `queryset.update()` reaches the
  CHECK and raises `IntegrityError`; all milestones on the same day are accepted. The corrected
  sample and all existing H-0a tests pass unchanged.

Local PostgreSQL was unavailable. GitHub Actions PostgreSQL run **36302848887** passed in **1m 5s**
on implementation commit `e36ec92`, including migration application, deployment checks, privacy
guards, and the complete Django suite. H-0a.1 took **0.06 elapsed hours** from pre-flight through
the passing implementation gate and report update.
