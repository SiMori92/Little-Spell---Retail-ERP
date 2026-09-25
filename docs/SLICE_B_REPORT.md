# Slice B report — posting engine

Date: 2026-09-25. Source repository: `SiMori92/Little-Spell---Retail-ERP`.
Scope: SAMPLE-mode accounting schema, frozen-event posting rules, controls, and seed command. No statements, close workflow, console, notifications, or contract edits.

## Preflight and a contract count conflict

All eight required preflight artifacts existed before code changes. `event_catalogue_FROZEN.md` has the v1.2 header and Addenda A, B and C. `../state/coa.csv` contained 74 data rows and remained read-only. A non-transactional 74-code snapshot under `acct/data/` was generated from source SHA-256 `c282a2bc5b7d24fd0b0b8c11fe854ec1d619c7501ae4e34de09ac3fa02de4a20` for repeatable deployment; no `../state/` file was written.

**The task says 29 posting rules, but frozen v1.2 explicitly says 28 event types** (22 ops, 6 accounting-originated), and `acct_data_contract.md` §8 numbers them 1–28. The 29 in the task cannot be reconciled to a named frozen event. The writer has exactly 28 name-bound rules, with an assertion that this equals both model catalogues. An unknown name raises `PostingError`. No 29th event was invented.

## Implemented controls

- `acct` now has Account, JournalEntry, JournalLine, AcctManualEntry, FxRate, Period, and a per-SKU WacPosition. The six accounting-originated events live only in AcctManualEntry. The accounting writer never inserts an ops LedgerEvent; `acct_writer` has no INSERT privilege on that table.
- JournalLine debit/credit are numeric(18,4) functional TWD. The nullable transaction triple has the specified CHECK. Deferred balance checks sum by `entry_id` only. A test posts an entry whose USD transaction leg is not currency-balanced but whose TWD journal is; Postgres accepts it.
- The first accounting migration executes the exact journal `REVOKE UPDATE, DELETE ... FROM PUBLIC, ops_writer, acct_writer`. Entry and line UPDATE/DELETE are also rejected by triggers, including for the table owner. Manual facts are immutable; only posting status/error metadata may change under the application owner, and `acct_writer` has no UPDATE grant. `apply_table_grants` preserves those restrictions.
- A CLOSED accounting period rejects an entry and a new line into an existing entry. Reserved account codes reject journal lines. Revenue accounts require tax treatment in the account table.
- The public and Etsy channel rates have separate FxRate rows and different allowed `rate_source` values. Settlement refuses a missing `channel_applied_fx_rate`, missing evidence, a USD deposit, or a derived rate inconsistent with TWD deposited / USD settled. Its spread line is 6116; a test rejects any 7111 line on that path. 7111 remains available to the separate reversal/bank-movement path, and 7112 to revaluation.
- The seed command requires a positive integer TWD amount **and** an opening date. It posts only Dr 1121 / Cr 3111 in SAMPLE mode. `--reverse` posts one reversing entry and clears the seed handle. No amount is embedded in code.
- G-1 counts both event tables and treats either a null posting link or non-null error as a failure. Ops `posting_error` was migrated from empty-string default to nullable so the SQL condition has its specified meaning.
- The public-repo guard now applies `SENSITIVE_NAMES` to tabular filenames only; a concept-named migration is allowed, and the hook test still passes.

The DDU/unknown-duty branch creates a **memo-only acknowledgement record** linked from `posted_entry_id`, with zero financial lines. This keeps G-1 from treating an acknowledged non-financial event as lost while avoiding a fake zero-value debit/credit. The acknowledgement lives in the JournalEntry table for linkage, so the phrase “no journal entry” in §8.1 should be clarified in the next contract revision to mean “no financial journal lines.”

## Rate archive check

The official Bank of Taiwan archive displayed a dated 2025-03-27 page with a CSV download link: <https://rate.bot.com.tw/xrt/all/2025-03-27>. The linked endpoint was `https://rate.bot.com.tw/xrt/flcsv/0/2025-03-27`. A direct fetch returned an HTML **Challenge Validation** page, not CSV bytes. Therefore historical CSV **retrievability and parseability were not proven**, despite the download link. No automatic fetch was built. `load_public_fx_rate` is an evidence-backed manual loader; each entered rate is marked `manual` and the supplied evidence reference is required. A later automatic loader must verify the response type and parse a dated archive before marking a rate `bot`.

## Rule coverage and sample reachability

Synthetic tests produced balanced entries for **20 postable ops rules and all 6 manual rules**. The two payment rules intentionally raise because 1193 is RESERVED. The DDU/unknown branch of rule 7 produces the memo-only acknowledgement. These results demonstrate mechanical posting shapes only, not real-world amounts.

| Frozen rules | Current sample status |
|---|---|
| 1 `order.placed` | Five sample orders exist. Public rates are not loaded, and three seller-mapped discounts conflict with gross Sale rail amounts; those must block. Two no-discount paths are structurally reachable after a supported public rate and fixture verification. |
| 2 `order.fees_assessed` | Fee rows exist, but the Slice A payload lacks the channel-applied rate required by Addendum C; blocked. |
| 3 `order.shipped` | Ship dates exist. Revenue posting depends on a consistent held deposit and public order rate; the three conflicting discounted orders cannot be posted as-is. |
| 4 `order.cogs_relieved` | Dispatch events exist, but no sourced SKU WAC position exists; blocked. Provisional cost is not silently accepted as actual. |
| 14 `settlement.received` | The sample deposit is USD to a USD account and lacks the required Etsy rate. Addendum C says this sample path is unrepresentative; blocked. |
| 22 `cost.recorded` | One Listing Fee period cost exists and routes to Dr 6115 / Cr 1191. It still needs a public rate and verified fixture before a real fixture posting can be claimed. Advertising without channel attribution blocks. |
| 5–13 (except the four above), 15–21 | No corresponding event rows in the sample. The payment pair (12–13) is additionally blocked by reserved 1193. Rule 21 is seed-only, not a sample import event. |
| 23–28 | No accounting-originated sample events. Synthetic only. |

**Zero posting rules are claimed as verified against real fixtures.** Slice A deliberately marks its schema fixtures unverified, and no marker was changed. Tests use synthetic, non-customer rows; the existing Slice A importer test uses an in-memory override to test import mechanics, not a founder sign-off. The sample also cannot reach a TWD Etsy deposit, 6116 from a real settlement, a refund, a reversal, a PO landed-cost path, a domestic taxable sale, non-zero platform-remitted tax, a real SKU WAC, or the six manual events. These are source gaps, not passing financial controls.

## Verification and remaining limits

`python manage.py test` passed **97 tests** on local Postgres. The suite covers each postable rule's TWD arithmetic, the two reserved payment failures, unknown names, all three role denials on journal UPDATE/DELETE, the owner append-only trigger, closed-period admission, FX-leg balance, rate-source distinction, settlement refusal/spread, seed missing amount, both G-1 negative streams, and the hook. No test prints a customer row.

This slice does not assert G-2 through G-5 or financial statement correctness; those are close/report work. The public-rate command relies on manually supplied evidence until the official archive CSV can be fetched and parsed. The sample importer does not supply Addendum C rate fields and does not establish actual WAC. Its contract and importer changes belong to Agent 1; this repo did not edit `../contracts/*` or treat a sample schema as verified. No production deployment or founder seed amount was attempted.
