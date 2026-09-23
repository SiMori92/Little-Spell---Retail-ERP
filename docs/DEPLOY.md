# Deploying to Railway — `uat`

One environment, named `uat`. KICKSTART §0.3: two environments on Hobby eat the $5
credit, and with zero orders there is only synthetic data to protect.

## The rule that comes with one environment

> **No real customer or order data enters this environment until a second
> environment exists.**

KICKSTART §0.3. The day the first real Etsy export is imported, this UAT silently
becomes production — and a single-environment production with `main` auto-deploying
migrations is how you lose your books.

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
