# Deploying to Railway — `uat`

The original environment is named `uat` and remains SAMPLE permanently. When going live, create the
separate `production` environment described below; it has its own web service, secrets, and empty database.

## The rule that comes with one environment

> **No real customer or order data ever enters the UAT environment.**

UAT is not converted in place. Production starts separately, so SAMPLE rows can never sit beside real rows.

**This rule also belongs in `../RUNBOOK.md`**, which is outside this repository and
which this build deliberately did not edit. Copy it across.

Railway deploys from **`SiMori92/Little-Spell---Retail-ERP`**, the public
repository selected by the founder on 2026-09-23. The old
`SChiu-project/Little-Spell---Retail-ERP` private repository is a separate copy;
commits pushed only there do not update this Railway deployment.

## Services

| Service | Notes |
|---|---|
| `web` | this repo, Dockerfile build |
| `Postgres` | Railway plugin |
| `worker` | **DEFERRED to Slice A** by founder decision, 2026-09-21. Do not create it now. |

**On the worker — decided.** BUILD_TASK §4.2 specifies web + worker + postgres, and
that is right *eventually*: the worker runs the importers and the posting engine.
Neither exists yet, so in Slice 0 it would read no queue, run no task, and still bill
against the $5 Hobby credit every hour. **Founder decision, 2026-09-21: deferred to
Slice A.** Create `web` and `Postgres` only.

## Variables — on the `web` service

| Variable | Value |
|---|---|
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` — a **reference**, never a pasted string |
| `DJANGO_SECRET_KEY` | a **NEW** key. Not the one in local `.env`. |
| `DJANGO_DEBUG` | `0` |
| `DJANGO_DB_SSL_REQUIRE` | `1`. Set to `0` **only** if the deploy fails with *"server does not support SSL"* — see below. |

`RAILWAY_PUBLIC_DOMAIN` is injected by Railway; `settings.py` appends it to
`ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` automatically.

**Apply variable edits:** Railway stages new and changed variables. On the project
canvas, review the staged-change banner and click **Deploy**. A GitHub push can
deploy new code while variable edits are still staged, leaving the running container
without `DATABASE_URL`. Check the resulting pre-deploy log before retrying the web
service. See [Railway's variable guide](https://docs.railway.com/variables) and
[staged changes guide](https://docs.railway.com/deployments/staged-changes).

**Check the database reference:** `DATABASE_URL` on the Django service must resolve
to the *Postgres service's* `DATABASE_URL`. `${{DATABASE_URL}}` is a self-reference
and can resolve to an empty string; a separate variable called `web` does nothing
for Django. If the reference selector shows no Postgres service, verify that a
PostgreSQL service exists in this same Railway environment. Add one from
**+ New → Database → PostgreSQL** if absent, then use
`${{Postgres.DATABASE_URL}}` on the Django service. Do not paste a raw connection
string into the repository or a screenshot.

### If the pre-deploy migrate fails with "server does not support SSL"

`DATABASE_URL` from `${{Postgres.DATABASE_URL}}` resolves to Railway's **private**
hostname `postgres.railway.internal`, which does not always terminate TLS. With
`DJANGO_DEBUG=0` the app asks for `sslmode=require`, and the pre-deploy `migrate`
then fails.

That failure is the pre-deploy slot doing its job — the deploy stops instead of
crash-looping a half-migrated app. The fix is one variable, not a code change:

    DJANGO_DB_SSL_REQUIRE=0

Set it **only** while `DATABASE_URL` points at `*.railway.internal`, which never
leaves Railway's private network. If that URL is ever repointed at a public host,
set it back to `1`.

Generate the new key:

```bash
uv run python -c "import secrets; print(secrets.token_urlsafe(50))"
```

## Deploy commands

`railway.json` already sets these, so the dashboard does not need to. If you prefer
the dashboard, the values are identical:

| Setting | Value |
|---|---|
| Pre-deploy | `uv run python manage.py migrate && uv run python manage.py apply_table_grants` |
| Start | `uv run gunicorn config.wsgi --bind 0.0.0.0:$PORT` |
| Healthcheck | `/healthz` |

**Migrations go in the PRE-DEPLOY slot.** In the start command, a failed migration
crash-loops a half-migrated app instead of failing the deploy (KICKSTART §12).

`apply_table_grants` follows `migrate` because `ALTER DEFAULT PRIVILEGES` cannot
filter by table-name prefix — see `core/dbroles.py`.

## Troubleshooting the first deploy

### `ImproperlyConfigured: Required environment variable DJANGO_SECRET_KEY is not set`

The variable is missing on the **web service**. Set the four variables above and
redeploy. The app refuses to start rather than inventing a key, because a generated
fallback key boots an application whose sessions and signatures are worthless — and
boots it silently.

### Gunicorn is crash-looping instead of the deploy failing

**This means the pre-deploy command is not running.** If it were, `migrate` would hit
the same misconfiguration first and fail the deploy, and gunicorn would never start.

Check **web service -> Settings -> Deploy** and confirm the pre-deploy command is
actually registered:

    uv run python manage.py migrate && uv run python manage.py apply_table_grants

`railway.json` sets it, but a value entered in the dashboard, or config-as-code not
being picked up for the service, will override or bypass it. This matters beyond the
current error: it is the difference between a bad migration failing the deploy and a
bad migration leaving a half-migrated database serving traffic (BUILD_TASK §4.3).

Symptom to watch for: the deploy logs show gunicorn booting but contain **no
`Applying ...` migration lines at all**.

## First deploy

```bash
railway login
railway link                 # select the project, environment `uat`
# Settings -> Networking -> Generate Domain, then open https://<domain>/admin
railway run python manage.py createsuperuser
railway logs
```

## Backups

```bash
ops_scripts/backup.sh --uat
ops_scripts/restore_test.sh ~/ledger-backups/uat-<stamp>.sql.gz
```

Restore-test it and write the elapsed time into `docs/SLICE_0_REPORT.md`.
An untested backup is a belief, not a control.

## Going live

Production is a separate Railway environment, with a separate web service and a new, empty PostgreSQL
database. Never flip the UAT database: it has held SAMPLE rows and stays SAMPLE permanently.

1. In Railway, create an environment named `production`. Inside that environment create a new web service
   from `SiMori92/Little-Spell---Retail-ERP` and add a new PostgreSQL service. Do not clone or attach the UAT
   database.
2. Generate a key that has never been used by UAT or locally, and generate a separate database password:

   ```bash
   uv run python -c "import secrets; print(secrets.token_urlsafe(50))"
   uv run python -c "import secrets; print(secrets.token_urlsafe(40))"
   ```

3. Set production web variables: `DJANGO_SECRET_KEY` to the first generated value,
   `DATABASE_URL=${{Postgres.DATABASE_URL}}`, `DJANGO_DEBUG=0`, and the appropriate
   `DJANGO_DB_SSL_REQUIRE`. Set the new Postgres password on the production Postgres service. Never paste
   either secret into this repository, evidence text, command output, or a ticket.
4. Link the CLI to the `production` environment and initialise only the empty production database:

   ```bash
   railway link
   railway environment production
   railway run uv run python manage.py migrate
   railway run uv run python manage.py apply_table_grants
   railway run uv run python manage.py createsuperuser
   railway run uv run python manage.py record_secret_rotation \
     --actor '<founder-or-operator>' \
     --evidence-ref '<vault-rotation-record>' \
     --db-password-rotated
   ```

5. Preview every go-live precondition. Opening funding type is mandatory and is never defaulted:

   ```bash
   railway run uv run python manage.py flip_dataset_to_actual \
     --amount '<opening-TWD-to-4dp>' \
     --funding-type '<capital-or-loan>' \
     --actor '<founder-or-operator>' \
     --evidence-ref '<signed-opening-funding-evidence>' \
     --dry-run
   ```

   Every line must say `PASS`. Resolve any `FAIL`; do not bypass or edit the database flag.

6. Run the same command without `--dry-run`:

   ```bash
   railway run uv run python manage.py flip_dataset_to_actual \
     --amount '<opening-TWD-to-4dp>' \
     --funding-type '<capital-or-loan>' \
     --actor '<founder-or-operator>' \
     --evidence-ref '<signed-opening-funding-evidence>'
   ```

7. Load ACTUAL master data and the complete opening count, in this exact order, then post its emitted event:

   ```bash
   railway run uv run python manage.py import_suppliers --file suppliers_YYYY-MM-DD.csv --commit
   railway run uv run python manage.py import_products --file products_YYYY-MM-DD.csv --commit
   railway run uv run python manage.py import_counts --file count_YYYY-MM-DD.csv --commit
   railway run uv run python manage.py post_accounting_event ops '<opening-count-ledger-event-id>'
   railway run uv run python manage.py import_po --file po_PO-YYYY-NNN.csv --commit
   ```

The supplier and product files must both be ACTUAL files loaded after the flip. This preserves the
Product→Supplier provenance chain before the first PO. The opening count is single-use; a second
`inventory.opening_counted` posting is refused.
