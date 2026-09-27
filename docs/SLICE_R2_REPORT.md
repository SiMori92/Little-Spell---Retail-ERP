# Slice R-2 — Damaged stock in a count

Date: 2026-09-28 HKT

Branch: `main`

Gate base: `3183e0d`

Implementation commit: `59afaad`

PostgreSQL 16 CI run: `36333253893` — PASS

Real elapsed build time: 0.5 hours

## Result

Count intake now uses `(sku, condition)` as its line key while retaining the unchanged
`counts_header_v2` columns. Every active SKU requires a sellable row. A positive, nil-cost damaged row
may accompany that sellable row and is persisted on `StockCountLine`, but it is carried only in
`damaged_lines[]`: it creates no `InventoryMove`, no journal line and no WAC quantity or value.

The event catalogue remains exactly 28 events. Opening counts post only sellable value. Later counts
continue to compare book sellable pieces with counted sellable pieces and write downward differences to
`5121`; upward adjustments remain refused. The PostgreSQL `ops_on_hand` view was replaced in migration
`ops.0015_damaged_stock_count` so legacy count movements that can be identified as damaged-only are
excluded, while new damaged rows never create a movement at all.

The inventory report now includes `Damaged pieces held (latest count)` with SKU, pieces, count date and
evidence reference, plus the fixed instruction: `Held pending the 記帳士. Do not destroy.` A missing count
or a latest count with no damaged row renders `ABSENT` with the same provenance markers used by the other
CSV report figures.

## Frozen catalogue E.5 and E.6 — quoted in full

> ## E.5 · Ruled 2026-09-26 at GATE F — damaged stock is counted, not available
>
> **The Slice F build found that `condition` had no consumer** and said so rather than inventing one:
> *"the frozen catalogue records `damaged_unsellable` but has no separate availability account or stock
> class; a positive damaged count still contributes to the existing per-SKU on-hand view."*
>
> **It is right, and two things go wrong at once if it stands.** Reorder points are computed against
> stock that cannot be sold, so the system advises against reordering something you effectively have
> none of. And inventory value carries goods with no revenue ahead of them, overstating the balance
> sheet while hiding a loss that has already happened.
>
> ### The ruling, split where the ownership splits
>
> > **Orchestrator — the interface.** `condition` is not decoration. A line with
> > `condition = damaged_unsellable` is **excluded from the on-hand view** used for reorder points and
> > `avg_daily_units`. It remains counted, evidenced and valued. **It is not available.**
> >
> > **Agent 2 — the account.** Which account carries damaged stock, and whether the write-down falls at
> > the count or at disposal. `5121` exists for shrinkage and may or may not be the right home. **The
> > orchestrator does not rule an account's meaning** — §6.4 gives that to Agent 2.
>
> **Until Agent 2 rules, an intake carrying a non-zero `damaged_unsellable` line REFUSES**, naming the
> open ruling. **Counting damaged stock into sellable on-hand is worse than refusing to post it**, and
> a refusal is visible where a silent inclusion is not.
>
> **Consequence for the founder's first physical count:** count damaged stock separately as Addendum
> A3.1 already instructs, but **hold those lines out of the intake file** until the account is ruled.
> The sellable lines can be posted immediately.
>
> No event type is added, changed or removed. Still 28.
>
> ## E.6 · Amendment 2026-09-27 (v1.9) — damaged stock: the payload shape, on Agent 2's R-3
>
> **Supersedes in E.5:** "It remains counted, evidenced and **valued**" and the interim refusal. Agent 2's R-3
> (2026-09-27) rules the account: **write down at the count to `5121`; damaged pieces never enter `1231` or WAC.**
> This amendment is the interface that carries it. **Orchestrator ruling, §6.4.**
>
> 1. **Line key = `(sku, condition)`.** `condition ∈ {sellable, damaged_unsellable}`. A repeated `(sku, condition)`
>    is refused, as a repeated SKU was.
> 2. **Every active SKU still needs a `sellable` line, explicit zero allowed.** A `damaged_unsellable` line is
>    optional, `qty_pieces > 0`, and `agreed_unit_cost_twd` **must be `0.0000`**. Anything else is refused.
>    A damaged line alone, without a sellable line for the SKU, is refused. Nobody counted the shelf.
> 3. **A damaged line is a memo.** It is carried in the payload as `damaged_lines[]` (`sku`, `qty_pieces`) and
>    recorded on the count. It posts **no journal line**, creates **no inventory move**, and never reaches
>    on-hand, WAC or `avg_daily_units`. The schedule total is the sum of the **sellable** line values.
> 4. **`inventory.opening_counted`:** only sellable lines are debited to `1231`/`1233`. Damaged pieces at opening
>    never entered the books, so there is nothing to write down.
> 5. **`inventory.adjusted` (every later count):** the adjustment is **book sellable → counted sellable**. The
>    shortfall is written down **Dr `5121` · Cr `1231`** at WAC, as today. The pieces that are now damaged are
>    inside that shortfall. That **is** R-3's write-down at the count. An upward adjustment is still refused.
> 6. **Physical custody:** the memo is what the founder shows the 記帳士. Damaged stock is held, segregated and not
>    destroyed until the 記帳士 answers (Agent 2, R-3). The inventory report lists damaged pieces held per SKU
>    from the latest count.
>
> No event type is added, changed or removed. Still 28.

## Refusal messages

The R-2 intake refusals are:

```text
count <sku> condition must be sellable or damaged_unsellable
count file repeats (sku, condition): <sku>, <condition>
count <sku> damaged_unsellable qty_pieces must be greater than zero
count <sku> damaged_unsellable agreed_unit_cost_twd must be exactly 0.0000
count damaged_unsellable line for <sku> requires a sellable line for the same SKU
count file omits active SKU sellable line(s): <sorted SKUs>; use explicit zero rows
count <sku> implies an increase; a receipt is needed, not an adjustment
```

The posting boundary also refuses malformed or incorrectly routed damaged payloads:

```text
opening count <sku> lines must be sellable
opening count damaged_lines must be a list
opening count damaged_lines needs nonblank SKUs
opening count damaged_lines repeats SKU <sku>
opening count damaged_unsellable <sku> qty_pieces must be positive whole pieces
opening count damaged_unsellable <sku> requires a sellable line for the same SKU
inventory adjustment damaged_lines must be a list
inventory adjustment damaged_lines needs nonblank SKUs
inventory adjustment damaged_lines repeats SKU <sku>
inventory adjustment damaged_unsellable <sku> qty_pieces must be positive whole pieces
payload field qty_pieces is required
```

The unchanged per-line and schedule-value refusals remain:

```text
opening count <sku> line_value_twd disagrees with quantity and cost
opening count total_value_twd disagrees with sum of lines
```

The final message above is emitted at both the posting and pre-emission boundaries; both boundaries are
retained and tested.

## Expected ledgers — line by line

### Opening count: sellable 10 @ 10.0000; damaged 2 @ 0.0000

`inventory.opening_counted`, `TS-MN-006-P`, count date 2026-10-04:

```text
1231  TS-MN-006-P  qty +10  Dr 100.0000  Cr   0.0000
3111  —             qty   —  Dr   0.0000  Cr 100.0000
```

There is no `5121` line. The damaged memo posts no line. One opening `InventoryMove` exists for +10
sellable pieces and 100.0000 value; none exists for the two damaged pieces. On-hand is 10 and WAC is
10 pieces / 100.0000 value, or 10.0000 per piece.

### Later count: book sellable 12 @ WAC 10.0000; counted sellable 9; damaged 2

`inventory.adjusted`, `TS-MN-006-P`, count date 2026-10-05:

```text
5121  TS-MN-006-P  qty   —  Dr 30.0000  Cr  0.0000
1231  TS-MN-006-P  qty   -3 Dr  0.0000  Cr 30.0000
```

The only adjustment `InventoryMove` is -3 pieces / -30.0000. The damaged memo creates no additional
movement. On-hand is 9; WAC remains 10.0000 per piece with 9 pieces / 90.0000 value. The latest-count
damaged section reports 2 pieces at 2026-10-05 with evidence `COUNT-LATER`. The inventory report's SKU
row and total both report `TIES` after the opening and again after the later count.

All monetary assertions use exact `Decimal` values at 0.0001 precision.

## Tests touched

- `ops/test_slice_r2.py` — new. Covers I-1 through I-7, all four required damaged-row refusals, invalid
  condition, both duplicate-condition keys, explicit-zero sellable rows, unchanged per-line valuation,
  opening and later ledger lines, no damaged movement/journal/WAC/on-hand quantity, upward refusal,
  PostgreSQL on-hand result, latest-count reporting, CSV provenance, ABSENT markers and G-3 after each count.
- `ops/test_slice_f.py` — changed the pre-E.6 zero-quantity damaged fixture to a zero-quantity sellable row;
  zero damaged rows are now correctly invalid, while the original explicit-zero and re-import assertions
  continue to test the intended sellable behavior.
- `acct/test_slice_f.py` — changed the pre-E.6 zero-quantity damaged posting fixture to sellable and added
  `damaged_lines: []`; the existing zero-pair, WAC, total mismatch and one-opening-only assertions remain.

No other test file was changed.

## Verification

Local non-database checks:

```text
PYTHONPYCACHEPREFIX=/private/tmp/r2-pycache .venv/bin/python -m compileall -q core acct ops
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --check --dry-run
python3 -m unittest tests.test_pre_commit_hook
python3 tools/repo_guard.py --mode staged --check paths
python3 tools/repo_guard.py --mode staged --check content
git diff --check
```

The local host had no PostgreSQL client or service available, so no SQLite fallback was used. GitHub
Actions run `36333253893` used PostgreSQL 16, applied `ops.0015_damaged_stock_count`, ran the complete CI
sequence and completed successfully:

```text
Ran 299 tests in 54.455s
OK
```
