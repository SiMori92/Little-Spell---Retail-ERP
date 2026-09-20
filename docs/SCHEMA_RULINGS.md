# SCHEMA RULINGS

Rulings already made. **Do not re-litigate.** They are recorded here in Slice 0 so that
Slice A (ops subledger) and Slice B (general ledger) inherit them rather than rediscover them.

None of these are implemented in Slice 0 — Slice 0 has no business tables. This file is the
inheritance mechanism, not the implementation.

Source: `../BUILD_TASK_01_ops_ledger_build_plan.md` §3.4 (rev. 3), and the founder's
Slice 0 build instruction.

---

1. Money is exact decimal. numeric(18,4) or integer minor units. NEVER a float.
   No suspense account and no rounding account, ever.

2. acct journal line `debit` and `credit` hold the FUNCTIONAL TWD amount and nothing else.

3. The transaction leg is a SEPARATE nullable triple: txn_amount numeric(18,4),
   txn_currency char(3), fx_rate_id. Under:
   CHECK (txn_currency IS NULL OR txn_currency = 'TWD'
          OR (txn_amount IS NOT NULL AND fx_rate_id IS NOT NULL))

4. The balance trigger asserts SUM(debit) = SUM(credit) grouped by entry_id ALONE.
   NEVER by (entry_id, currency). Entries carrying an FX leg balance in functional
   currency and deliberately do NOT balance per-currency.

5. Any report in transaction currency sums txn_amount filtered by txn_currency.
   It NEVER sums debit/credit.

6. Revenue is recognised at DISPATCH, evidenced by a ship_date on the shipment row.
   order.placed debits the rail and credits 2211 deferred revenue. It NEVER credits revenue.

7. uom = PK (pack) for every SKU. Pack_Qty is a product attribute, never a quantity
   multiplier. Quantities everywhere are in packs.

8. Reporting and functional currency is TWD. USD transactions are recorded, not converted
   at entry. Realised FX to 7111, unrealised to 7112.

---

## Deferred to Slice B — recorded here so it is not lost

`REVOKE UPDATE, DELETE ON acct_journalentry, acct_journalline FROM PUBLIC, ops_writer,
acct_writer;`

This is the line that makes the books defensible (BUILD_TASK §3.1, KICKSTART §1). It cannot
run in Slice 0 because those tables do not exist yet. It is a **Slice B migration**, to land in
the same migration that creates the journal tables. See `acct/migrations/0001_initial.py`
for the placeholder comment carrying the same note.
