# Little Spell — Retail ERP

GitHub repository: **`Little-Spell---Retail-ERP`**. The Python project is named `tattoo-ledger`
(`pyproject.toml`), and the Django project package is `config`. The three names are
independent; only the repository name changed.

Operational ledger and financial reporting for a one-person Taiwan
temporary-tattoo-sticker business.

Slices 0–D established the operational ledger, posting, reporting and close gates.
Slice F adds evidenced receipt and physical-count intake plus read-only admin views.
The source schema fixtures remain `verified:false`, so `--commit` refuses until
the founder verifies the headers against real source files.

## Why this repo lives in `app/`

The parent folder contains `state/customers.csv`, which carries buyer names and
street addresses. A git repository at the parent root, pushed to GitHub, publishes
them. The repository root is therefore `app/` and nothing above it is tracked.

## Layout

| Path | What it is |
|---|---|
| `config/` | Django project: settings, urls, wsgi |
| `core/` | Platform infrastructure — dataset quarantine, audit log, DB roles |
| `ops/` | Operational tables and manifest-driven Etsy, receipt and count intake. |
| `acct/` | Journal, catalogue posting, reports and close gates. |
| `ops_scripts/` | backup and restore-test shell scripts |
| `docs/` | schema rulings, deploy guide and slice reports |

`ops` and `acct` ARE the segregation of duties. Django prefixes tables with the app
label, giving `ops_*` and `acct_*`, and grants are made by prefix. There are no
separate Postgres schemas — see `docs/SCHEMA_RULINGS.md` and `core/dbroles.py`.

## Read before changing the schema

**`docs/SCHEMA_RULINGS.md`.** Eight rulings that are already settled — money as exact
decimal, functional-vs-transaction currency, the balance trigger's grouping, revenue
at dispatch. Slices A and B inherit them. Do not re-litigate them.

## Local setup

Requires Postgres 16 and [uv](https://docs.astral.sh/uv/).

```bash
brew install postgresql@16 uv
brew services start postgresql@16
export PATH="/opt/homebrew/opt/postgresql@16/bin:$PATH"

cp .env.example .env
git config core.hooksPath .githooks
uv run python -c "import secrets; print(secrets.token_urlsafe(50))"   # into .env
createdb tattoo_ledger

uv sync
uv run python manage.py migrate
uv run python manage.py apply_table_grants
uv run python manage.py createsuperuser
uv run python manage.py runserver
```

`.env` is gitignored and must never be committed.

The pre-commit hook scans staged paths and content before a commit is created.
Run `git config core.hooksPath .githooks` once per clone. For a deliberate local
exception, use `ALLOW_DATA_COMMIT=1 git commit ...`; the hook prints a loud warning
with every staged filename. CI still rejects guarded paths and content, and a push
to this public repository can expose data before CI runs. Never use the exception
for customer data or a secret.

The `migrate` step creates the `ops_writer`, `acct_writer` and `reporter` roles, so
the database user running it needs `CREATEROLE`.

## Tests

```bash
uv run python manage.py collectstatic --noinput   # WhiteNoise manifest
uv run python manage.py test
```

## Slice A Etsy dry-run

The filenames identify the dataset kind. The application begins in `SAMPLE`.
This repository contains sanitized regression fixtures (customer fields blank)
so a fresh clone can run the dry-run without the founder's private workspace:

```bash
uv run python manage.py import_etsy \
  --orders tests/fixtures/SAMPLE_etsy_orderitems_2025-12_fixture.csv \
  --statement tests/fixtures/SAMPLE_etsy_statement_2025-12_fixture.csv
```

The dry-run prints counts, order IDs for reconciling items, and blockers. It never
prints customer rows. A founder-maintained `../state/coupon_funding.csv` may be
supplied with `--coupon-funding PATH`; it needs `coupon_code,funded_by,valid_from,valid_to`
columns, with ISO dates and `seller` or `platform` for discounted orders. The
importer reads this file but never creates or edits it. The unverified schema
fixtures prevent `--commit` even if a coupon map is present. See
`docs/SLICE_A_REPORT.md` for the unresolved contract and coverage gaps.

## Slice F receipt and count intake

Both commands dry-run by default and print counts only. Their expected private
source directories are `../inbox/receipts/` and `../inbox/counts/`; never copy
those files into this public repository. Each command accepts one file:

```bash
uv run python manage.py import_receipts --file ../inbox/receipts/SAMPLE_receipts_2025-03.csv
uv run python manage.py import_counts --file ../inbox/counts/SAMPLE_count_2025-03-27.csv
```

The receipt header is
`occurred_on,category,amount_twd,settled_via,evidence_ref,description`, optionally
followed by `channel_attribution,bank_account` in that order. Each evidence reference
identifies one receipt. Advertising requires a channel. Receipts never use
`etsy_rail` or `platform_listing_fee`.

The count header is
`counted_at,evidence_ref,sku,qty_packs,agreed_unit_cost_twd,condition`.
Repeat the same date and evidence reference on every row, with one row for **every**
product SKU. Write `0` explicitly for a counted zero. The first count emits one
opening schedule; later counts can only reduce stock through `inventory.adjusted`.
An increased quantity needs a receipt. Adjustments use the posted WAC value; their
CSV cost is retained as count evidence, not substituted into the journal.

`SAMPLE_*.csv` names are SAMPLE. ACTUAL names must be `receipts_YYYY-MM.csv` or
`count_YYYY-MM-DD.csv`, with dates agreeing with the rows. Other names are refused.
`--commit` stays locked while `schemas/receipts_header_v1.json` and
`schemas/counts_header_v1.json` are unverified. See `docs/SLICE_F_REPORT.md`.

## Sample-data quarantine

While `core_datasetsettings.dataset_kind = 'SAMPLE'`, every page renders a
**SAMPLE DATA — NOT ACTUALS** banner. This is a code path with tests behind it, not a
convention — deleting the banner fails the suite.

Clearing it requires reversing the seed journal entry and posting a real opening
entry:

```bash
uv run python manage.py flip_dataset_to_actual --amount <TWD>
```

It refuses today, and will keep refusing until Slice B exists. That refusal is the
control working.
