# tattoo-ledger

Operational ledger and financial reporting for a one-person Taiwan
temporary-tattoo-sticker business.

**This repository is at Slice 0: infrastructure only.** There are no orders, no
inventory, no lots, no shipments, no purchase orders, no journals, no accounts and no
customers. That is deliberate — Slice 0 is plumbing, and modelling orders before the
deploy pipeline works means debugging both at once.

## Why this repo lives in `app/`

The parent folder contains `state/customers.csv`, which carries buyer names and
street addresses. A git repository at the parent root, pushed to GitHub, publishes
them. The repository root is therefore `app/` and nothing above it is tracked.

## Layout

| Path | What it is |
|---|---|
| `config/` | Django project: settings, urls, wsgi |
| `core/` | Platform infrastructure — dataset quarantine, audit log, DB roles |
| `ops/` | Agent 1's domain. **Empty in Slice 0.** Slice A fills it. |
| `acct/` | Agent 2's domain. **Empty in Slice 0.** Slice B fills it. |
| `ops_scripts/` | backup and restore-test shell scripts |
| `docs/` | schema rulings, deploy guide, Slice 0 report |

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
uv run python -c "import secrets; print(secrets.token_urlsafe(50))"   # into .env
createdb tattoo_ledger

uv sync
uv run python manage.py migrate
uv run python manage.py apply_table_grants
uv run python manage.py createsuperuser
uv run python manage.py runserver
```

`.env` is gitignored and must never be committed.

The `migrate` step creates the `ops_writer`, `acct_writer` and `reporter` roles, so
the database user running it needs `CREATEROLE`.

## Tests

```bash
uv run python manage.py collectstatic --noinput   # WhiteNoise manifest
uv run python manage.py test
```

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
