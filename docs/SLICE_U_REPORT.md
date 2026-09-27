# Slice U report — the inventory unit becomes the piece (with U.1 fix)

Slice U: `81c9867` (PROMPT 10). U.1 fix: `9190362`, `21c99ad`, `473ec9d` plus the commit carrying this
report (PROMPT 10b). SAMPLE mode throughout. Catalogue still v1.6, 28 event types.

## 1. U.1: what was wrong and what changed

| # | Defect | Root cause | Fix |
|---|---|---|---|
| U-1 | Migration `ops/0011` crashed on any database holding a product | The data step ran `Product.objects.update(uom="PC")` while `ops_product_pack_uom` (`uom = 'PK'`) was still in force | Operations reordered (below). The uom rewrite now has a reverse (`uom = 'PK'`), so the migration also unapplies over populated products |
| U-2 | `ops.test_slice_g0.ComplianceFailClosedTests` errored (7) | **Two causes.** (a) At the 0007 state, `assert_po_eligible` loaded the whole live `Product` model, which now selects `pieces_per_sale_unit`, a column that does not exist yet. CI run `36306747425` shows 7 × `ProgrammingError: column ops_product.pieces_per_sale_unit does not exist`. (b) The test's cleanup migrates forward through 0011 with a product present, which hit U-1 | (a) `ops/compliance.py` (`21c99ad`) selects only the compliance columns the guard reads (`sku`, `ingredient_ref`, `supplier_id`, `supplier__declaration_ref`). The guard's logic is unchanged. (b) Fixed by U-1. **The test file is unchanged** (`git diff 8b9edbd HEAD -- ops/test_slice_g0.py` touches only `SliceG0Tests`, not this class) |
| U-3 | `inventory.adjusted` with the old `qty` was refused only by a generic message | The rule checked for missing fields together | `acct/posting.py` `inventory_adjusted` now refuses `qty` first: *"inventory adjustment payload field qty was renamed to qty_pieces (catalogue Addendum F.2)"*. A missing `qty_pieces` is refused separately: *"inventory adjustment qty_pieces is required"* |
| found by grep | `templates/home.html` metric card said "Recorded pack movements" | Label missed in `81c9867` (PROMPT 10 item 7) | Now "Recorded piece movements" |
| test hygiene | `UnitMigrationRefusalTests` errored when run alone (`core_auditlogentry_pkey` duplicate). This happens at `21c99ad` too | `reset_sequences = True` rewound the audit-log sequence while audit rows from test-DB creation remained. CI passed only because of test order | `reset_sequences` removed (`473ec9d`) |

**Operation order in `ops/0011` now:**

1. `RunPython(refuse_unsafe_data)`: the I-7 check, before anything changes.
2. All eight `RemoveConstraint` operations: `ops_product_pack_uom`, `ops_product_positive_pack_qty`,
   `ops_ig_deal_qty_positive`, `ops_line_positive_qty`, `ops_line_total_identity`, `ops_move_nonzero`,
   `ops_move_sign_discipline`, `ops_move_value_sign`.
3. `RunPython(rewrite_product_uom, restore_product_uom)`: the only data rewrite.
4. `RenameField` × 5, then `AlterField` × 2.
5. All eight `AddConstraint` operations (piece/sale-unit names), then the `ops_on_hand` view column rename
   and the Instagram trigger. `acct/0007` runs after `ops/0011` and has its own removes before renames
   before adds. It rewrites no data.

In `81c9867` the rewrite ran inside step 1, before the `PK` check was dropped. `9190362` moved it after the
first `RemoveConstraint` only. U.1 puts it after every removal, and a test now enforces the order.

**Tests added in U.1** (`ops/test_slice_u.py`):

- `test_populated_factor_one_database_migrates_forward_in_place` (I-9). At 0010 it seeds two factor-1
  products, one factor-12 product with no quantity rows, and one factor-1 opening move of 7. It migrates
  to 0011 and asserts: every product is `PC` with its factor kept (1, 1, 12); the move reads
  `qty_delta_pieces = 7` with value 35; the `ops_on_hand` view reads `qty_pieces = 7`; and the new
  `ops_product_piece_uom` check is live in the database.
- `test_factor_twelve_inventory_move_refuses_with_verbatim_i7_message` (I-9 refusal, from `9190362`):
  a factor-12 SKU with a move. The full F.4 message is matched with `^…$`.
- `test_refusal_first_constraints_dropped_before_rewrite_and_added_after`: operation 0 is the refusal;
  every `RemoveConstraint` comes before the rewrite, and every `AddConstraint` after it.
- `test_inventory_adjusted_old_qty_is_refused_by_name` (U-3).

**Watched failing.** The U.1 tests were run against `81c9867`'s `0011` swapped back in. The I-9
forward test and `ComplianceFailClosedTests` both raised
`CheckViolation: new row for relation "ops_product" violates check constraint "ops_product_pack_uom"`,
the gate's own error. The order test also failed. With the fix, all pass.

**CI (PostgreSQL 16 service, no SQLite):** run **`36307363779`** on `473ec9d`: **201 tests, OK**.
<https://github.com/SiMori92/Little-Spell---Retail-ERP/actions/runs/36307363779>. The commit carrying this
report (label fix plus report) has its own CI run, listed in the PR/branch history. Local runs used PostgreSQL
16.2: 201 tests, OK.

**Elapsed.** This U.1 session ran about 16:40–17:00 +0800 on 2026-09-27 (≈ 20 min wall clock,
including the before/after pipeline runs). `9190362` and `21c99ad` were committed at 16:36 and 16:38, before
this session. `81c9867` was committed at 16:16.

## 2. I-7 refusal on a populated SAMPLE database

The database was built at **`8b9edbd`** (the pre-U code) on PostgreSQL 16.2. It holds the real SAMPLE
suppliers and products (`docs/samples`), a v1 opening count, and the Etsy December fixture pair, all posted.
The U.1 code was then deployed against it with `python manage.py migrate`:

```
Running migrations:
  Applying ops.0011_piece_inventory_unit...Traceback (most recent call last):
RuntimeError: Unit migration refused: SAMPLE data holds pack quantities for TS-FS-004-P, TS-HN-007-M, TS-KD-008-P, TS-MN-006-P. Reset the SAMPLE database and re-import the samples (catalogue Addendum F.4).
```

Afterwards the database was still at `ops.0010`. `TS-MN-006-P` still read `uom = PK, pack_qty = 12`, so
nothing had changed. `TS-KD-008-P` is listed because its explicit zero-count row is a unit-bearing row.

**Success path by hand.** This was the Railway case: a database at `8b9edbd` holding the ten SAMPLE products
(factors 1, 2, 5, 10, 12) and no quantity rows.

- `migrate`: `ops.0011 … OK`, `acct.0007 … OK`. All ten products read `PC` with their factor kept.
- `migrate ops 0010`: both unapplied OK, and the products read `PK` again.
- `migrate` again: OK.
- `81c9867`'s `0011` against the same database raised
  `CheckViolation … "ops_product_pack_uom"` (U-1 reproduced).

## 3. I-4 / I-5: revenue, fees, contribution and COGS, before and after

**Method.** The same pipeline ran twice on an empty PostgreSQL database: once at `8b9edbd` (packs), once at
the U.1 head (pieces). Each run imports suppliers and products, then an opening count dated 2025-12-01, then
the Etsy fixture pair (`tests/fixtures/SAMPLE_etsy_*_2025-12_fixture.csv`), then posts every event, then runs
`contribution_orders("2025-12")`. Only the count file differs:

| SKU | factor | before (v1): qty_packs × cost/pack | after (v2): qty_pieces × cost/piece | value |
|---|---|---|---|---|
| TS-FL-001-S | 1 | 10 × 40 | 10 × 40 | 400 |
| TS-SL-003-L | 1 | 5 × 90 | 5 × 90 | 450 |
| TS-HN-007-M | 2 | 4 × 30 | 8 × 15 | 120 |
| TS-FS-004-P | 5 | 3 × 60 | 15 × 12 | 180 |
| TS-MN-006-P | 12 | 2 × 120 | 24 × 10 | 240 |
| other five SKUs | — | explicit 0 rows | explicit 0 rows | 0 |

Every per-piece cost is exact at 4 dp, so nothing was rounded. The same gate-only inputs were used in both
runs, because the SAMPLE set lacks them: a public USD rate of 31.5000 for 2025-12-01 and 12-28…31; a
`channel_applied_fx_rate` of 31.500000 on the fee and settlement events (the Etsy export carries none);
and coupon funder `platform` for the three coupon codes (the statement's Sale amount equals gross, and
`seller` is refused by `order.placed`).

**Result, NT$, before (8b9edbd) / after (U.1):**

| Order | Product revenue | Shipping revenue | Seller discount | Etsy fees | Product COGS | Packaging COGS | Contribution |
|---|---|---|---|---|---|---|---|
| 2918473019 | 818.3700 / 818.3700 | 157.1850 / 157.1850 | 0.0000 / 0.0000 | 100.4850 / 100.4850 | 80.0000 / 80.0000 | 0.0000 / 0.0000 | ABSENT / ABSENT |
| 2918473022 | 787.1850 / 787.1850 | 204.7500 / 204.7500 | 0.0000 / 0.0000 | 221.4450 / 221.4450 | 90.0000 / 90.0000 | 0.0000 / 0.0000 | ABSENT / ABSENT |
| 2918473035 | 377.6850 / 377.6850 | 173.2500 / 173.2500 | 0.0000 / 0.0000 | ABSENT / ABSENT | 30.0000 / 30.0000 | 0.0000 / 0.0000 | ABSENT / ABSENT |
| 2918473050 | 535.1850 / 535.1850 | 173.2500 / 173.2500 | 0.0000 / 0.0000 | 5.6700 / 5.6700 | 60.0000 / 60.0000 | 0.0000 / 0.0000 | ABSENT / ABSENT |
| 2918473062 | 1,227.5550 / 1,227.5550 | 173.2500 / 173.2500 | 0.0000 / 0.0000 | ABSENT / ABSENT | 120.0000 / 120.0000 | 0.0000 / 0.0000 | ABSENT / ABSENT |

**Every figure is identical to the NT$ (to 0.0001),** and so are the report notes. A programmatic diff of
the two outputs found no field that differs.

- **COGS (I-5).** FS-004-P: 1 pack × 60 before, 5 pcs × 12 after, NT$60 both. HN-007-M: 1 × 30 before,
  2 × 15 after, NT$30 both. The factor-1 SKUs are unchanged. The inventory roll-forward moves from
  "Sold packs" 8 to "Sold pcs" 13 (FS 1 → 5, HN 1 → 2). GL inventory value is NT$1,010.0000 in both runs.
- **Contribution is ABSENT in both runs, for every order.** That is the fail-closed rule: outbound
  freight, duty position and the FX settlement spread do not exist in the SAMPLE set. So it is equal but
  unproven as a number. For the three orders with known fees, revenue + shipping − discount − fees − COGS
  (a derived cross-check, not a system figure) is NT$795.0700, 680.4900 and 642.7650 in both runs.
- **Fees ABSENT** for 2918473035 and 2918473062: the statement fixture has no fee rows for those orders.
- In both runs one event stays unposted, for a reason unrelated to units:
  `settlement.received: required payload field rate_source is missing`.
- **2 × TS-MN-006-P relieves 24 pieces:** `acct.test_slice_b` has
  `test_two_ts_mn_sale_units_relieve_twenty_four_pieces_without_changing_cogs`. It credits 1231 with
  `qty_delta_pieces = -24` and NT$120.

**Observation for the gate.** `81c9867`'s own I-4/I-5 test (`ops.test_slice_a`
`test_pre_u_sample_economics_snapshot_is_identical_in_pieces`) is weak evidence. It works in USD, not NT$.
Its costs are hard-coded in the test. It never runs posting or the reports, and it computes "before" and
"after" with the same code. The pipeline comparison above is the real I-4/I-5 proof. The test was not
rewritten in U.1 (no scope change).

## 4. Test files changed

### In `81c9867`

No numeric expected value was changed in an existing test. Every change is one of three kinds:
(a) a field or key rename per Addendum F.2; (b) `Product` fixtures moving from `uom="PK"` to `uom="PC"`
with `pieces_per_sale_unit=1` (the new required field; factor 1 keeps every quantity the same); or
(c) a new test.

| File | Changes | Expected values changed? |
|---|---|---|
| `acct/test_slice_b.py` | Product `PK`→`PC` + factor 1; `qty_packs`→`qty_sale_units`/`qty_pieces`; `qty_delta_packs`→`qty_delta_pieces`; `inventory.adjusted` payload `qty`→`qty_pieces`; `position.qty_packs`→`qty_pieces`. New: `test_two_ts_mn_sale_units_relieve_twenty_four_pieces_without_changing_cogs`, `test_old_pack_payload_names_are_refused` | No. The COGS 8.0000, the WAC 4 / 32.0000 and the 20-rule count are unchanged |
| `acct/test_slice_c.py` | Product `PK`→`PC` + factor 1 (lines 73–74, 230); `qty_packs`→`qty_sale_units` (order lines); count payload and move renames | No. Contribution 173.0000 is unchanged |
| `acct/test_slice_d.py` | `qty_delta_packs`→`qty_delta_pieces`; Product `PC`; G-3 detail keys `ops_packs`/`gl_packs` → `ops_pieces`/`gl_pieces` (lines 132, 140, following `acct/gates.py`) | Key names only. Quantities 5, 3, −1, −2 are unchanged |
| `acct/test_slice_f.py` | Product `PC` + factor 1; count `qty_packs`→`qty_pieces`; assertions read `qty_delta_pieces`/`qty_pieces` | No. `[3, None, 0, None]`, 37.5 and 0 are unchanged |
| `ops/test_slice_a.py` | Product `PC` + factor 1; move renames; `OnHand.qty_packs`→`qty_pieces` (the value `100 − 3 + 2` is unchanged); test renamed `…signed_pack_movements`→`…signed_piece_movements`. New: `test_pre_u_sample_economics_snapshot_is_identical_in_pieces` (see §3) | No |
| `ops/test_slice_f.py` | Product `PC` + factor 1; count header `qty_packs`→`qty_pieces`; assertions on `StockCountLine.qty_pieces` / `qty_delta_pieces` (0). New: `test_fractional_piece_count_is_refused_by_field_name` (7.5). Line 181 keeps `"uom": "PK"` as the *attempted* admin change that must be refused (403) | No |
| `ops/test_slice_g0.py` | `SliceG0Tests` only. Test renamed `…fractional_pack…`→`…invalid_conversion…`; case `pack_qty: "1.5"` → `pieces_per_sale_unit: "1.5"`, expected message `pack_qty must be…` → `pieces_per_sale_unit must be…` (lines 129–130, field name in the message). New: `test_zero_conversion_is_refused_by_intake_and_database`. `ComplianceFailClosedTests` is untouched: it seeds `uom="PK", pack_qty=1` at the 0007 state, which is correct for that schema | Message text only; it names the renamed field |
| `ops/test_slice_h0a.py` | Instagram row key `qty_packs`→`qty_sale_units` (lines 49, 54, 141) | No. `"1"`, `"2"` unchanged |
| `ops/test_slice_u.py` | New file | — |

### In U.1 (`9190362`, `21c99ad`, `473ec9d`)

Only `ops/test_slice_u.py` changed.

- `9190362` split the single migration test into three. Its target moved from `acct.0007` to `ops.0011`,
  because the refusal lives in `ops.0011` and `acct.0007` depends on it.
- `21c99ad` added a tearDown that clears the historical rows when a refusal left the database at 0010.
- `473ec9d` extended the factor-1 test into the I-9 populated test and removed `reset_sequences`. It also
  added the order test and the U-3 test.

**No test in any other file was changed in U.1.** `ops/test_slice_g0.py` in particular was not touched.

## 5. Grep inventory (tree at U.1 head)

`git grep` over tracked files in `app/`. Counts: `qty_packs` 32 · `pack_qty` 16 · `qty_delta_packs` 13 ·
`"PK"`/`'PK'` 11 · `uom` (word) 33 · `pack` (any case, substring) 182, of which 102 are `packag…` and 80 are
not. Hits are grouped below. Where a group covers every hit in a file, it says so.

### 5.1 Renamed (the hit performs or maps the rename)

| Hit | What |
|---|---|
| `ops/migrations/0011…py:146–150` | `RenameField`: `pack_qty`→`pieces_per_sale_unit`; `igdeal.qty_packs`, `orderline.qty_packs`→`qty_sale_units`; `qty_delta_packs`→`qty_delta_pieces`; `stockcountline.qty_packs`→`qty_pieces` |
| `ops/migrations/0011…py:213–214` | `ops_on_hand` view column `qty_packs`→`qty_pieces` (and reverse) |
| `ops/migrations/0011…py:122` | `IG_TRIGGER_V1` = the V2 trigger with `qty_sale_units` swapped back to `qty_packs`, used for the reverse only |
| `acct/migrations/0007…py:17–18` | `wacposition.qty_packs`→`qty_pieces`; `journalline.qty_delta_packs`→`qty_delta_pieces` |
| `ops/intake.py:64–66` | Old→new header map, so v1 files are refused naming both fields |

Live names after the rename (no old-name hit remains in any model, posting rule, intake, report or gate):
`Product.pieces_per_sale_unit` · `OrderLine.qty_sale_units` · `IgDeal.qty_sale_units` ·
`InventoryMove.qty_delta_pieces` · `StockCountLine.qty_pieces` · `OnHand.qty_pieces` ·
`WacPosition.qty_pieces` · `JournalLine.qty_delta_pieces` · posting payloads `qty_pieces`
(`inventory.opening_counted`, `inventory.adjusted`, `po.received`) · G-3 details `ops_pieces`/`gl_pieces`.

### 5.2 Converted (value or label changed, not just the name)

| Hit | What |
|---|---|
| `ops/models.py:44, 51` · `ops/file_intake.py:345` · `ops/admin.py:54` | `uom` default and check are `PC`; intake writes `PC`; the admin list shows `uom` beside `pieces_per_sale_unit` |
| `ops/migrations/0011…py:74, 80, 152, 158` | Data rewrite `uom = 'PC'` (reverse `'PK'`), new default, new `ops_product_piece_uom` check |
| `docs/SCHEMA_RULINGS.md:34` | Ruling 7 marked superseded: `uom = PC` |
| `docs/samples/SAMPLE_products_2026-09-27.csv` | Header v2; `pieces_per_sale_unit` = old `pack_qty` (1,1,1,1,5,1,12,2,10,1) |
| `acct/reporting.py` | Roll-forward labels "… pcs"; SKU contribution unit "sale units" (no `pack` hit remains) |
| `templates/home.html:16` | "Recorded pack movements" → "Recorded piece movements" (**U.1**) |

### 5.3 Deliberately unchanged, with reasons

| Hits | Reason |
|---|---|
| `ops/migrations/0001–0010`, `acct/migrations/0003–0006` (every `qty_packs`, `pack_qty`, `qty_delta_packs`, `'PK'`, `uom`, `ops_product_pack_uom`, `positive_pack_qty` hit in them, including the file name `0005_closerun_journalline_qty_delta_packs_and_more` and its reference at `acct/0006:9`) | Applied migration history. Django replays it to build the pre-U state, so editing it would change schema history. Slice U works only by adding `ops/0011` + `acct/0007` |
| `ops/migrations/0011…py:8, 26, 32, 50, 60, 137–138` | The refusal runs **before** the rename, so it must read the old columns (`pack_qty`, `qty_delta_packs`) and old payload keys (`qty_packs`, `qty`). The `RemoveConstraint` lines name the old constraints. `"…holds pack quantities…"` is the verbatim I-7 / F.4 message |
| `schemas/products_header_v1.json:5`, `counts_header_v1.json:5`, `ig_deals_header_v1.json:5` | Kept so v1 files are recognised and refused by name ("…uses header v1 (pack_qty); v2 requires pieces_per_sale_unit") |
| `ops/test_slice_u.py:31–36, 50–52` | Builds v1 headers to prove they are refused |
| `ops/test_slice_u.py:70` | The forbidden-name set the model test checks against |
| `ops/test_slice_u.py:121–166` (`pack_qty`, `qty_delta_packs`, `"PK"`, "pack") | Migration tests seed rows in the **0010 historical state**, where those are the real columns and values. Line 153 attempts `uom="PK"` after migrating, to prove the new check rejects it. Line 166 is the verbatim refusal message |
| `ops/test_slice_u.py:79` | Attempts `uom="PK"` to prove the database check rejects it |
| `ops/test_slice_g0.py:184` | `ComplianceFailClosedTests` seeds at the 0007 state (`uom="PK", pack_qty=1` are that schema's columns). U-2 required this test to stay unchanged |
| `ops/test_slice_f.py:181` | `"uom": "PK"` is the attempted admin edit that must be refused (403) |
| `acct/test_slice_b.py:242–255` | `test_old_pack_payload_names_are_refused` sends old payload names (`qty_packs`, `qty`) to prove refusal by name |
| `docs/SLICE_A_REPORT.md:37`, `SLICE_C_REPORT.md:33–34`, `SLICE_F_REPORT.md:14, 45, 62`, `SLICE_G0_REPORT.md:88, 95, 110`, `SLICE_H0A_REPORT.md:36, 61` | Historical gate reports describe what those slices built under D-27. They are records and are not rewritten. `SCHEMA_RULINGS.md` and `UNIT_MIGRATION_U.md` carry the current rule |
| `acct/test_slice_*.py`, `ops/test_slice_*.py` `uom="PC"` hits (`acct/test_slice_b.py:23, 202`, `acct/test_slice_c.py:73–74, 230`, `acct/test_slice_d.py:99`, `acct/test_slice_f.py:16`, `ops/test_slice_a.py:46`, `ops/test_slice_f.py:26, 178`, `ops/test_slice_g0.py:151`) | Already converted; listed because `uom` was a search term |
| `docs/SLICE_G0_REPORT.md:19` | Historical mention of `Product` fields |
| Every `packag…` hit (102): `acct/posting.py` ×5, `acct/reporting.py` ×4, `acct/test_slice_b.py` ×3, `acct/data/coa_snapshot.json` ×2, `docs/SLICE_0/C/D_REPORT.md`, `README.md`, `pyproject.toml`, `uv.lock` ×81 | *Packaging* materials (accounts 1233 / 5114, the `packaging` landed-cost component) or Python *package* metadata. Not the inventory unit |
| `Dockerfile:3`, `docs/SLICE_0_REPORT.md:283` | "Nixpacks" (Railway's builder), a substring match |

This report itself also contains every search term, because it is the inventory. No other hit exists.
