# Slice G-3 report — pay suppliers

**Status:** complete · **dataset:** SAMPLE only · **branch:** `main` · **implementation commit:**
`0a1661cc26e40bc88c7a2e6e8029ca35192b99dc` · **PostgreSQL CI:** run `36321822018`, PASS,
280 tests · **real elapsed time:** 0.6 hours (20:44–21:18 HKT, 2026-09-27).

Pre-flight passed at `17f352f1bdfab22a6f4e738fd891a03ba9342d45`: the repository was on `main`, the
worktree was clean, that commit was HEAD, and every required contract/code/report file existed. All writes were
inside `app/`.

## 1. Addendum H — quoted in full

> # ADDENDUM H · 2026-09-27 · v1.8 — supplier deposits and payments
>
> **Ruled by Agent 0 under §6.4.** Accounting basis: Agent 2's **R-2** (`acct_open_decisions.md` rev. 4): a deposit is a
> prepayment in **`1266`**, it never debits `2171`, it is cleared at receipt pro rata by value, and it is aged by PO and
> zero at PO close. **The event count stays 28:** the deposit leg rides on existing events.
>
> ## H.1 `po.paid` gains `payment_kind`
>
> | `payment_kind` | When | Entry |
> |---|---|---|
> | `deposit` | PO `sent`/`acknowledged`, **before any receipt** | Dr `1266` · Cr `1121` |
> | `balance` | Against a **posted** supplier invoice | Dr `2171` · Cr `1121` |
> | `deposit_refund` | Cancelled PO, the supplier returns the deposit | Dr `1121` · Cr `1266` |
> | `deposit_forfeit` | Cancelled PO, the deposit is lost (evidence mandatory) | Dr `6199` · Cr `1266` (R-2.5) |
>
> Every row carries `po_number`, `bank_ref` (except `deposit_forfeit`) and `evidence_ref`. **TWD and `1121` only:** a
> non-TWD deposit is a `posting_error` until ruled (R-2.6, IFRIC 22). A missing `payment_kind` is a `posting_error`,
> never a default.
>
> ## H.2 `po.received` applies the deposit
>
> `deposit_applied_twd` adds a self-balancing pair to the receipt entry: **Dr `2171` · Cr `1266`**. It sits outside the
> G.5.1 identity, which is unchanged.
>
> - **Amount = deposits paid on the PO × this receipt's line value ÷ PO value**, both excluding tax, half-up at 4 dp.
> - The cumulative total is capped at the deposits paid.
> - **The receipt that completes the PO applies the exact remainder.**
> - If the supplier's invoice states a different application, the **computed** amount is posted and the difference is
>   **listed** for reconciliation, not posted. The vendor's net position (`2171 − 1266`) is identical under either
>   method (R-2.3).
>
> ## H.3 Controls
>
> 1. **Deposits paid on a PO ≤ PO value excluding tax.** A deposit on a PO with any receipt is refused.
> 2. **Balance payments on an invoice ≤ invoice total − deposit applied to it.** Overpayment is refused, never carried
>    as a debit on `2171`.
> 3. **Close gate G-2 adds `1266`:** any PO at `received`/`short_closed`/`cancelled` with a non-zero `1266` balance
>    **fails G-2**, naming the PO.
>
> ## H.4 Renumbering
>
> The wallet addendum (BUILD_TASK_03 §1.5) becomes **Addendum I (v1.9)**.
>
> No event type is added, changed or removed. **Still 28.**

## 2. Payment source contract

Expected private intake directory: `inbox/po_payments/` (not created inside the public application repository).
Accepted filenames are `SAMPLE_pay_<payment_ref>.csv` in SAMPLE mode and `pay_<payment_ref>.csv` in ACTUAL mode.
There is exactly one payment row per file. `schemas/pay_header_v1.json` is authored and verified. The command is:

```text
python manage.py import_supplier_payment --file <path> [--commit]
```

Dry-run is the default. Exact columns, in order:

| # | Column | Rule |
|---|---|---|
| 1 | `payment_ref` | `^[A-Z0-9][A-Z0-9-]{0,31}$`; equals the filename reference; unique per dataset |
| 2 | `paid_on` | ISO `YYYY-MM-DD` |
| 3 | `supplier_ref` | Must equal the named PO's supplier |
| 4 | `po_number` | Required existing PO |
| 5 | `invoice_no` | Required only for `balance`; blank for the other three kinds |
| 6 | `payment_kind` | Exactly `deposit`, `balance`, `deposit_refund`, or `deposit_forfeit`; never defaulted |
| 7 | `amount_twd` | Positive decimal, at most 4 dp |
| 8 | `bank_account` | Exactly `1121` (R-2.6) |
| 9 | `bank_ref` | Required except for `deposit_forfeit`, where it must be blank |
| 10 | `evidence_ref` | Required; PII-screened |

`SupplierPayment` inherits `Provenance`, is append-only in both model and PostgreSQL, and retains the PO, supplier,
optional invoice, payment kind, amount and evidence. Re-importing an identical row is a no-op; changing a previously
imported row is refused.

## 3. Posting and state transitions

`po.paid` requires the kind, PO, evidence, TWD and `1121` in the posting rule itself. Its entries are exactly H.1.
The intake additionally proves the PO/invoice state and refuses an amount that would overdraw `1266` or make supplier
`2171` a debit. Account `1266` is installed from R-2 by `acct.0008` because the Slice B database snapshot predated
the founder-owned chart's R-2 row.

For every matched receipt, `ops.receiving.deposit_application` computes:

```text
deposits paid × receipt invoice-line value excluding tax ÷ PO value excluding tax
```

It rounds half-up to four decimal places, caps the cumulative amount at deposits paid, and gives the exact remaining
amount to the receipt that completes the PO. The emitted `po.received` payload carries both
`deposit_applied_twd` (computed and posted) and `invoice_stated_deposit_twd` (recorded only). The posting engine adds
Dr `2171` / Cr `1266` outside the unchanged G.5.1 identity.

Receipt completion still moves the PO to `received` or `short_closed`. A subsequent payment moves it to `closed`
only when its `1266` balance is zero and every supplier invoice is fully paid. `cancelled` and `closed` are terminal;
`received`/`short_closed` may move only to `closed`. PostgreSQL enforces the forward path and the close conditions.

## 4. Every G-3 refusal message

`<…>` denotes source data inserted into a fixed message. Shared CSV-boundary messages are included because the new
payment source uses that boundary.

| Control | Refusal message |
|---|---|
| filename | `Unclassified pay filename: <name>` |
| dataset quarantine | `Filename <name> is SAMPLE; application dataset_kind is ACTUAL` (and the reverse) |
| header | `Header mismatch in <name>; expected pay v1 exact columns; missing=[…]; added=[…]; order_changed=<bool>` |
| column count / encoding | `Wrong CSV column count in <name>` · `Cannot parse UTF-8 CSV <name>: <error>` |
| schema lock | `Cannot --commit: pay schema fixture is unverified` · `pay schema fixture must have source authored` |
| row count | `payment file <name> must contain exactly one row` |
| reference | `payment_ref must match ^[A-Z0-9][A-Z0-9-]{0,31}$: <value>` · `payment_ref <a> does not match filename payment reference <b>` |
| required fields | `<field> is required` |
| date / money | `paid_on must be ISO YYYY-MM-DD` · `amount_twd must be a decimal amount` · `amount_twd must be nonnegative with at most 4 decimal places` · `amount_twd must be positive` |
| kind | `payment_kind is required; it never defaults (catalogue H.1)` · `unknown payment_kind <kind>; expected deposit, balance, deposit_refund or deposit_forfeit (catalogue H.1)` |
| invoice shape | `balance payment requires invoice_no` · `<kind> payment requires invoice_no to be blank` |
| bank evidence | `<kind> payment requires bank_ref` · `deposit_forfeit has no bank_ref` |
| R-2.6 | `bank_account <account> is refused; supplier payments are TWD through 1121 only (R-2.6, IFRIC 22)` · `PO <po> currency <currency> is refused; supplier payments are TWD through 1121 only (R-2.6, IFRIC 22)` |
| PII | `PII detected in <column>` (the value is never echoed) |
| idempotency | `Previously imported supplier payment <ref> has changed; supplier payments are append-only` |
| identity | `unknown PO: <po>` · `payment supplier_ref <a> disagrees with PO <po> supplier <b>` |
| deposit timing | `deposit requires PO <po> at sent or acknowledged; it is <status>` · `deposit on PO <po> is refused after a receipt exists (catalogue H.3.1)` |
| deposit cap | `deposit would make cumulative deposits on PO <po> exceed PO value excluding tax <amount>` |
| balance prerequisite | `balance payment requires posted supplier invoice <invoice> on PO <po>` · `balance payment requires posted supplier invoice <invoice>` |
| overpayment | `balance payment <amount> overpays invoice <invoice>; open amount is <open>; 2171 must never go debit for a supplier` |
| cancellation | `<deposit_refund|deposit_forfeit> requires cancelled PO <po>; it is <status>` |
| open 1266 | `<deposit_refund|deposit_forfeit> <amount> exceeds open 1266 balance <open> on PO <po>` |
| posting boundary | `supplier payment posting rule refused: <posting error>` |

Posting-rule errors, which set the event's posting failure boundary rather than guessing a kind/account, are:

```text
required payload field payment_kind is missing
unknown payment_kind; expected deposit, balance, deposit_refund or deposit_forfeit
required payload field po_number is missing
required payload field evidence_ref is missing
supplier payments are TWD through bank account 1121 only (R-2.6, IFRIC 22)
deposit_forfeit has no bank_ref
<kind> payment requires bank_ref
required payload field amount_twd is missing
required payload field invoice_no is missing
```

The G-2 temporary invoice refusal
`INV <invoice> deposit_applied_twd must be 0; supplier deposits arrive with G-3` was deliberately removed. A non-zero
invoice-stated amount is now recorded and reconciled, never substituted into the computed posting.

## 5. PO-2026-002 ledger — deposit through close

All master data and transaction files in `docs/samples/g3/` are **synthetic SAMPLE fixtures**, including SUP-002,
TS-MT-005-S, TS-FS-004-P and declaration paths such as
`compliance/suppliers/SAMPLE_SUP-002_decl.pdf`. They are not actual supplier, product, compliance, bank or invoice
records.

| Step | Journal line | Debit | Credit | Result |
|---|---|---:|---:|---|
| DEP-002 | `1266` · PO deposit | 38,700.0000 | | Deposit never touches `2171` |
| DEP-002 | `1121` · TWD bank | | 38,700.0000 | Open `1266` = 38,700.0000 |
| R1 / INV-A | `1231` · TS-MT-005-S, 3,000 pcs | 60,900.0000 | | Landed = 58,000 + 2,900 tax; 20.3000/pc |
| R1 / INV-A | `2171` · computed deposit application | 17,400.0000 | | 38,700 × 58,000 ÷ 129,000 |
| R1 / INV-A | `2171` · supplier invoice | | 60,900.0000 | Open INV-A / `2171` = 43,500.0000 |
| R1 / INV-A | `1266` · deposit applied | | 17,400.0000 | Open `1266` = 21,300.0000 |
| R2 / INV-B | `1231` · TS-FS-004-P, 7,500 pcs | 74,550.0000 | | Landed = 71,000 + 3,550 tax; 9.9400/pc |
| R2 / INV-B | `2171` · exact completing remainder | 21,300.0000 | | Completes PO receipt allocation |
| R2 / INV-B | `2171` · supplier invoice | | 74,550.0000 | Total open `2171` = 43,500 + 53,250 = 96,750 |
| R2 / INV-B | `1266` · deposit applied | | 21,300.0000 | Open `1266` = 0; PO is `received` |
| BAL-A | `2171` · pay INV-A | 43,500.0000 | | INV-A open = 0 |
| BAL-A | `1121` · TWD bank | | 43,500.0000 | |
| BAL-B | `2171` · pay INV-B | 53,250.0000 | | INV-B open = 0; `2171` for SUP-002 = 0 |
| BAL-B | `1121` · TWD bank | | 53,250.0000 | PO moves to `closed` |

Total credit to `1121` is **135,450.0000** = 38,700 + 43,500 + 53,250 = 60,900 + 74,550. Both `1266` for
PO-2026-002 and `2171` for SUP-002 finish at zero. The three-line rounding regression is
333.3333, 333.3333, and exact completing remainder 333.3334.

## 6. Reports and G-2

Three authenticated read-only reports were added:

- `/reports/payables/`: posted invoice total, computed deposit application, balance paid, open `2171`, and age by
  supplier/invoice.
- `/reports/supplier-deposits/`: deposits paid, applied, refunded, forfeited, open `1266`, and age from first deposit
  by PO.
- `/reports/deposit-reconciliation/`: only invoice-stated versus computed differences. The difference never posts.

G-2 now evaluates `1266` first. A `received`, `short_closed`, or `cancelled` PO with a non-zero balance returns FAIL
and names each PO and amount as:

```text
non-zero 1266 supplier deposit by PO: <PO>=<amount> (R-2.5, H.3.3)
```

The cancellation regression proves deposit 5,000, refund 3,000 and evidenced forfeit 2,000 reaches zero and passes
G-2 when its existing settlement-source prerequisite is present. The uncleared version fails naming the PO and
5,000.0000.

## 7. Verification and touched tests

GitHub Actions run `36321822018` used PostgreSQL 16 and passed all **280** tests. It also passed repository visibility,
tracked-path/content guards, the pre-commit-guard suite, Django system and deployment checks, migration-state check,
migrations, table grants and static collection. No SQLite fallback was used.

Existing tests touched, with the reason:

| Test file | Change | Reason |
|---|---|---|
| `acct/test_slice_b.py` | Generic `po.paid` balance fixture now supplies kind, amount, PO, `1121`, bank and evidence | Addendum H.1 makes these mandatory; no default is permitted |
| `ops/test_slice_g2.py` | Removed the temporary database/intake refusal of non-zero invoice-stated deposit | G-3 I-5 explicitly lifts that refusal and records the stated amount |
| `ops/test_slice_g2.py` | Changed the received-state database assertion from terminal to “only moves to closed” | G-3 adds `closed` after receipt plus zero `1266` and fully paid invoices |

New `ops/test_slice_g3.py` tests every I-1–I-9 refusal/control, exact H.1 entries, the PO-2026-002 ledger, NT$0.0001
overpayment refusal, post-receipt deposit refusal, pre-invoice balance refusal, stated/computed reconciliation,
cancellation clearing, G-2 pass/fail, report balances, PII, idempotency and four-decimal remainder behavior.
