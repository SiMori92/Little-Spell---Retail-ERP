# Slice J report — accounting-originated entries

Date: 2026-09-26. Source: public `SiMori92/Little-Spell---Retail-ERP` repository.
Scope: six commands that create `AcctManualEntry` rows under catalogue v1.5. They
do not post. The posting rules, event types, model constraints, triggers, and
G-1/G-5 gates were not changed.

## Command-to-rule map

| Command | Existing `manual()` event/rule | Command-specific input and saved control |
|---|---|---|
| `accrue` | `period.accrued`: Dr expense, Cr 2191/2193/2197 | `--expense-account --accrual-account --amount --basis-note`; saves `basis=estimate` and the basis note. |
| `reverse_accrual` | `period.accrual_reversed`: Dr original payable, Cr original expense | `--reverses` must name a posted accrual; amount is copied from it. No `--amount` option. |
| `revalue` | `period.revalued`: loss Dr 7112/Cr named account; gain reverse | `--account --amount --direction --rate-source`; excludes inventory 1231/1232/1233. |
| `record_tax_assessed` | `tax.assessed`: Dr 6182/Cr 2194 | `--amount`; always saves `needs_prof_conf=True`. No disabling option. |
| `record_tax_paid` | `tax.paid`: Dr 2194/Cr 1121 | `--amount` and mandatory evidence reference. |
| `move_owner_funds` | `owner.funds_moved`: capital Dr 1121/Cr 3111; drawings Dr 3211/Cr 1121; loan Dr 1121/Cr 2281 | `--amount --funds-type {capital,drawings,loan}`. |

Every command also requires `--actor`, `--evidence-ref`, `--period YYYY-MM`,
`--occurred-on YYYY-MM-DD`; `--dry-run` prints the two exact TWD journal lines
from the existing `plan()` rule, with account codes and four-decimal amounts,
without saving a row. Creation prints the manual-entry ID and the separate
`post_accounting_event manual <id>` command. Idempotency key is
`manual:<event type>:<period>:SHA256(<evidence ref>)`, so it is independent of
the clock and row count and does not put the reference text into the key.
An identical rerun reports the existing ID; changed details under the same
natural key are refused.

## Refusals and enforcement layer

| Condition | Message or relevant text | Layer |
|---|---|---|
| Required option omitted, including actor/evidence on every command | argparse identifies the required option | Command parser, before DB |
| Actor/evidence/basis note/rate source/account option blank; actor over 80 or evidence over 255 characters | `--<name> is required and cannot be blank` / `--<name> exceeds <limit> characters` | Command |
| Bad period or date, or date outside period | `--period must be YYYY-MM`; `--occurred-on must be an ISO date YYYY-MM-DD`; `--occurred-on must fall inside period <period>` | Command |
| Accounting period closed | `accounting period <period> is CLOSED` | Command; DB period trigger remains backstop |
| Invalid amount (nonpositive, more than four decimal places, or beyond decimal(18,4)) | `--amount must be positive TWD with at most four decimal places and fit decimal(18,4)` | Command |
| Natural key reused with changed actor, amount, date, payload, or other entry details | `natural key already exists with different entry details; use a distinct evidence reference` | Command; unique DB key is backstop |
| Accrual account other than 2191/2193/2197 | `--accrual-account must be one of 2191, 2193, 2197` | Command; posting rule also refuses |
| Reversal target missing, wrong type or unposted | `--reverses needs a posted period.accrued manual entry` | Command; posting rule also refuses |
| Original accrual already reversed under another evidence reference | `accrual already reversed` | Existing posting rule called during command preview |
| Reversal amount differs | Operator cannot enter amount; original amount is copied. Existing rule still checks equality. | Command shape and posting rule |
| Inventory account revaluation | `inventory accounts 1231, 1232, 1233 cannot be revalued` | Command; posting rule also refuses |
| `--direction` or `--funds-type` outside enumerated choices, or unsupported flag such as `--amount` on reversal / professional flag on assessment | argparse `invalid choice` or `unrecognized arguments` | Command parser |
| Posting rule returns invalid lines, required account is absent/reserved | Posting rule message, `account <code> does not exist`, or `account <code> is RESERVED` | Command preview; reserved account is also checked on posting |
| DB insert race or constraint violation | `manual entry could not be created; check the natural key and period` | Database, surfaced by command |

The existing database CHECKs still enforce catalogue membership, tax evidence,
owner funds type, and a basis note key whenever `basis=estimate`. The command
requires a **nonblank** basis note before reading the database. The CHECK only
tests key presence, so the command is deliberately stricter. The append-only
trigger and explicit posting step remain in force. G-1 counts unposted manual
rows; G-5 checks estimates and source evidence during close.

## Verification and limits

- Django system check: passed.
- Migration check: no changes detected (database history check unavailable locally).
- Local PostgreSQL test attempt: blocked because no server is listening on
  `127.0.0.1:5432`; CI provides PostgreSQL 16 for database tests.
- Slice J database suite and full CI: pending.

Tests use synthetic actors, references, dates and amounts; they do not print
customer rows. SAMPLE data cannot establish a real accrual basis, confirm a
tax assessment with a 記帳士, prove a real exchange-rate source, or validate a
real voucher or bank movement. Operators must supply those references before
using the commands with actual records. `AcctManualEntry.first_flagged_on`
exists on the model but is read nowhere; this slice does not change or use it.

Elapsed implementation and verification time: pending final CI result.
