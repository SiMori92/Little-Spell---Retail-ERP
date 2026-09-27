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

---

# Slice R-2.1 — Packaging stock-count value goes to `1233`

Date: 2026-09-28 HKT

Resolves: `GATE_R2_RESULT.md` finding **F-1** (packaging counted into `1231`), against catalogue E.6 item 4 and
Addendum G.1/G.2.

Branch: `claude/packaging-stock-count-1233-8f9f8b`, fast-forwarded onto `main`

Gate base: `a9f7960`

| Commit | What | CI run (PostgreSQL 16) | Result |
|---|---|---|---|
| `e165cf8` | R-2.1 tests alone, old code | `36334276895` | FAIL: 5 failures, 4 errors, all in `ops/test_slice_r21.py` (I-4 passed; see below) |
| `07019c5` | I-4 hardened, old code | `36334413933` | FAIL: 6 failures, 4 errors. **All nine R-2.1 tests fail.** The other 298 pass |
| `b64d844` | The fix | `36334533154` | FAIL: 1 error, `ops/test_slice_a.py` fixture (see Tests touched) |
| `ce953f1` | Slice A fixture touched | **`36334670864`** | **PASS: `Ran 307 tests … OK`** |

**Implementation commit: `ce953f1`. PostgreSQL 16 CI run: `36334670864` — PASS.** No local PostgreSQL service
or client was available (no container runtime either), so every database run above is GitHub Actions. There was
no SQLite fallback.

Still **28** events (`acct/posting.py` asserts it at import). No migration. Nothing outside `app/` changed.

## Result

`inventory.opening_counted` and `inventory.adjusted` now choose their stock account from
`Product.product_type`, the same rule `po.received` uses (Addendum G.1): `packaging` → `1233`,
`sellable` → `1231`. The rule is `acct.posting.inventory_account_for(sku)`. A SKU that is not a product
refuses posting: `inventory SKU <sku> is not a known product`.

- **I-1 opening count.** Each sellable-condition line debits `1233` or `1231` by `product_type`. The credit
  (`3111`), per-line values, the zero-pair evidence and the total check are unchanged. Count intake now writes
  `inventory_account` onto every payload line. Posting re-derives it and refuses a line whose recorded
  account disagrees.
- **I-2 later count.** Intake records `inventory_account` in the `inventory.adjusted` payload. Posting derives
  it again from `product_type` and credits that account: packaging posts Dr `5121` / Cr `1233`, sellable stays
  Dr `5121` / Cr `1231`. A payload whose `inventory_account` disagrees is a `posting_error`, and so is one with
  no `inventory_account`. Neither is ever corrected: the event stays unposted with its payload as written, and
  no journal entry is created.
- **I-3 WAC.** `apply_wac` puts only the lines posted to `1231` into `WacPosition` on the opening count, and moves
  WAC on an adjustment only when the credit is `1231`. The `po.received` rule is unchanged. Packaging never has
  a `WacPosition`.
- **I-4 G-3.** `acct.gates.g3` passes after the opening count (packaging 1,000 pcs / 7,000.0000 on `1233`) and
  after the adjustment (990 pcs / 6,930.0000). Both figures are > 0.
- **I-5 damaged packaging.** Handled exactly as for a sellable SKU: a `damaged_lines[]` memo with no journal
  line, no move, no WAC. The damaged pieces sit inside the `1233` shortfall.

### I-3 — the packaging cost basis on `1233`, named

**Packaging 1233 book average (per SKU):** Σ value of the SKU-tagged `1233` journal lines ÷ Σ their
`qty_delta_pieces`, within the dataset (`acct.posting.packaging_book`). It is **not** a `WacPosition`, and
nothing writes one for packaging.

This is G-2's basis carried forward. G-2 posts each packaging receipt as Dr `1233` at its landed value with
`sku` and `qty_delta_pieces` (e.g. mailers 105,766.4234 for 15,000 good pieces, 7.0511/pc derived). The opening
count now posts the same tagged pair. A packaging shortfall is valued at that SKU's tagged `1233` value ÷
pieces, rounded half-up to 0.0001, then checked again at posting against the intake's `source_value_twd`.
For count intake, the packaging "position" is that `1233` book. It is checked against the SKU's
`InventoryMove` pieces, exactly as sellable WAC is.

## Expected ledgers (asserted to 0.0001)

### Opening count: `PKG-MAIL-LS` 1,000 @ 7.0000 · `TS-MN-006-P` 10 @ 10.0000

`inventory.opening_counted`, 2026-10-04:

```text
1233  PKG-MAIL-LS  qty +1000  Dr 7,000.0000  Cr     0.0000
3111  —             qty     —  Dr     0.0000  Cr 7,000.0000
1231  TS-MN-006-P  qty   +10  Dr   100.0000  Cr     0.0000
3111  —             qty     —  Dr     0.0000  Cr   100.0000
```

Totals: **Dr 1233 7,000.0000 · Dr 1231 100.0000 · Cr 3111 7,100.0000**. `WacPosition`: `TS-MN-006-P` only,
10 pcs / 100.0000. None for `PKG-MAIL-LS`. G-3: PASS.

### Later count: `PKG-MAIL-LS` 990 (book 1,000); `TS-MN-006-P` 10 (no change)

`inventory.adjusted`, 2026-10-05, payload `inventory_account = "1233"`, `qty_pieces = 10`,
`source_value_twd = 70.0000`:

```text
5121  PKG-MAIL-LS  qty    —  Dr 70.0000  Cr  0.0000
1233  PKG-MAIL-LS  qty  -10  Dr  0.0000  Cr 70.0000
```

No `1231` line. On-hand `PKG-MAIL-LS` 990. `1233` book 990 pcs / 6,930.0000. `TS-MN-006-P` WAC is still
10 pcs / 100.0000. G-3: PASS.

A sellable shortfall in the same set-up (`TS-MN-006-P` counted 7) still posts
Dr `5121` 30.0000 / Cr `1231` 30.0000, qty −3, and its payload records `inventory_account = "1231"`.

## New refusal messages

```text
inventory SKU <sku> is not a known product
opening count <sku> inventory_account <recorded> disagrees with product_type, which posts to <derived> (R-2.1)
inventory adjustment inventory_account is required (R-2.1)
inventory adjustment inventory_account <recorded> disagrees with product_type of <sku>, which posts to <derived> (R-2.1)
inventory adjustment lacks sufficient SKU packaging stock on 1233
```

## Watching each invariant fail

On the old code, runs `36334276895` / `36334413933`:

| Test (`ops/test_slice_r21.py`) | Inv. | On `a9f7960` code |
|---|---|---|
| `test_i1_opening_count_debits_1233_for_packaging_and_1231_for_sellable` | I-1 | ERROR `KeyError: 'inventory_account'` (no account recorded; the ledger had `1231` for packaging) |
| `test_i1_payload_inventory_account_disagreeing_with_product_type_refuses` | I-1 | FAIL `PostingError not raised` |
| `test_i2_later_packaging_shortfall_posts_5121_against_1233` | I-2 | ERROR `KeyError: 'inventory_account'` |
| `test_i2_sellable_shortfall_stays_on_1231_and_records_its_account` | I-2 | ERROR `KeyError: 'inventory_account'` |
| `test_i2_disagreeing_or_missing_inventory_account_is_a_posting_error` (3 sub-tests) | I-2 | FAIL ×3 `CommandError not raised` |
| `test_i3_packaging_never_enters_sellable_wac` | I-3 | FAIL: a `WacPosition` existed for `PKG-MAIL-LS` |
| `test_i4_g3_ties_with_packaging_on_1233_after_opening_and_adjustment` | I-4 | FAIL (second run only; see below) |
| `test_i5_damaged_packaging_is_a_zero_value_memo_as_for_sellable` | I-5 | ERROR `KeyError: '1233'` (no `1233` line) |

Two things to state plainly:

- **I-4's first version passed on the old code (run `36334276895`).** G-3 nets `1231+1232+1233` per SKU, so it
  ties even with packaging misposted to `1231`. G-3 passing alone cannot prove I-4. The test now also asserts
  that the packaging value and pieces are on `1233`, and that the SKU has no `1231` line. That version fails
  on the old code (run `36334413933`) and passes on the fix.
- **The memo half of I-5 was already true at `a9f7960`.** R-2 posted no line and no move for any damaged row.
  The I-5 test fails on the old code only on the `1233` leg: damaged packaging behaves like sellable once the
  sellable packaging shortfall is on `1233`.

## Tests touched

- `ops/test_slice_r21.py` — **new**, 8 tests / 10 cases: I-1 to I-5, the expected figures, G-3 after the
  opening count and after the adjustment, and the posting-error path through `post_accounting_event`.
- `acct/test_slice_b.py` — `test_every_postable_ops_rule_balances`: the hand-built `inventory.adjusted` payload
  now carries `"inventory_account": "1231"` (`TESTSKU` is sellable). A payload without the field is now a
  posting error, by I-2.
- `ops/test_slice_a.py` — `test_all_22_ops_catalogue_types_are_emittable_without_posting`: creates a `Product`
  for its synthetic `SYNTHETIC` opening-count line. Emission dry-runs the posting rule. With no product there is
  no `product_type` to choose `1231` or `1233`, so the rule now refuses, correctly. Count intake already refuses
  unknown SKUs.

No other test file changed.

## Verification

Local non-database checks at `ce953f1`, all clean:

```text
manage.py check                                   System check identified no issues
manage.py makemigrations --check --dry-run        No changes detected
python3 -m unittest tests.test_pre_commit_hook    OK
tools/repo_guard.py --mode tracked --check paths  exit 0
tools/repo_guard.py --mode tracked --check content exit 0
git diff --check a9f7960 ce953f1                  clean
```

PostgreSQL 16 (GitHub Actions `36334670864`, head `ce953f1`): full CI sequence, **`Ran 307 tests … OK`**.
That is 299 from R-2 plus the 8 new tests.

## Open items (not changed by R-2.1)

1. **Packaging receipts create no `InventoryMove`** (G-2 report §8 item 2; `ops/receiving.py` skips non-`1231`
   rows). The opening count is correct. But after the first packaging `po.received`, the SKU's `1233` pieces
   exceed its move pieces. G-3 then fails for that SKU, and a later count refuses it:
   `count <sku> has no tied WAC/on-hand position`. That refusal is safe, not silent. **The first opening count is
   unaffected. Counting packaging after a packaging receipt needs receipt moves for `1233` rows.**
2. **`order.cogs_relieved` relieves `1233` by an untagged `packaging_twd` lump** (G-2 §8 item 2). Once one posts,
   G-3 is `NOT_RUNNABLE` (untagged inventory value), and the per-SKU `1233` book does not see that relief.
   Packaging relief per SKU still needs a ruling.
3. **A pre-R-2.1 `inventory.adjusted` event still unposted** now fails posting with
   `inventory adjustment inventory_account is required (R-2.1)`. Only SAMPLE data can hold one. It must be
   re-counted, not patched.
