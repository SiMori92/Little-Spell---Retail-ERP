# Little Spell — Retail ERP

GitHub repository: **`Little-Spell---Retail-ERP`**. The Python project is named `tattoo-ledger`
(`pyproject.toml`), and the Django project package is `config`. The three names are
independent; only the repository name changed.

Operational ledger and financial reporting for a one-person Taiwan
temporary-tattoo-sticker business.

Slice 0 established the infrastructure. Slice A adds operational tables and a
sample-only Etsy importer. The schema fixtures remain `verified:false`, so the
importer's `--commit` path refuses by design. No accounting journal, account table,
or posting engine exists yet.

## Why this repo lives in `app/`

The parent folder contains `state/customers.csv`, which carries buyer names and
street addresses. A git repository at the parent root, pushed to GitHub, publishes
them. The repository root is therefore `app/` and nothing above it is tracked.

## Layout

| Path | What it is |
|---|---|
| `config/` | Django project: settings, urls, wsgi |
| `core/` | Platform infrastructure — dataset quarantine, audit log, DB roles |
| `ops/` | Slice A operational tables and Etsy importer. |
| `acct/` | Agent 2's domain. **Empty in Slice 0.** Slice B fills it. |
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

The filenames identify the dataset kind. The application begins in `SAMPLE`, so
the provided sample files can be inspected with:

```bash
uv run python manage.py import_etsy \
  --orders ../inbox/etsy/SAMPLE_etsy_orderitems_2025-12.csv \
  --statement ../inbox/etsy/SAMPLE_etsy_statement_2025-12.csv
```

The dry-run prints counts, order IDs for reconciling items, and blockers. It never
prints customer rows. A founder-maintained `../state/coupon_funding.csv` may be
supplied with `--coupon-funding PATH`; it needs `coupon_code,funded_by,valid_from,valid_to`
columns, with ISO dates and `seller` or `platform` for discounted orders. The
importer reads this file but never creates or edits it. The unverified schema
fixtures prevent `--commit` even if a coupon map is present. See
`docs/SLICE_A_REPORT.md` for the unresolved contract and coverage gaps.

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
