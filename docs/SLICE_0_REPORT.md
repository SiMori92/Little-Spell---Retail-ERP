# SLICE 0 — BUILD REPORT

**Date:** 2026-09-21 · **Repository:** `app/` · **Commit:** `6bc39bd`
**Status: PARTIALLY COMPLETE.** Everything buildable on this machine is built,
verified and committed. Four items are outstanding, all of them blocked on things
only you can do: a sudo password, a GitHub login, and a paid Railway account.

---

## 1. The done-list, item by item

| # | Item | Status | How it was verified |
|---|---|---|---|
| 1 | `/admin` loads over HTTPS on the Railway domain, and I can log in | **NOT DONE** | Blocked — no Railway project exists. Verified equivalently on localhost: HTTP 200 at `/admin/` after a real form login as superuser `founder`. |
| 2 | Three roles + `ALTER DEFAULT PRIVILEGES` applied to the `uat` database | **DONE locally, NOT on uat** | Applied by migration `core/0002`. Queried `pg_roles`: all three exist with LOGIN. Queried `pg_default_acl`: two entries. `uat` does not exist yet. |
| 3 | Trivial model change → commit → push → Railway deploy → migration in logs | **NOT DONE** | Blocked — no GitHub remote, no Railway project. |
| 4 | `pg_dump` taken **and restored**, elapsed time written down | **DONE** | See §3. **Restore elapsed: 0.04 s.** |
| 5 | `.env` and `state/` absent from the GitHub repo — checked | **DONE for the repo contents, NOT on GitHub** | See §4. The repo has not been pushed, so there is nothing on GitHub to check yet. |
| 6 | The SAMPLE banner renders, and its test FAILS when the banner is removed | **DONE** | See §5. Sabotaged three different ways; each broke the suite. |
| 7 | CI green on push | **NOT DONE** | Workflow written. All ten steps replayed locally and pass. Cannot be green until pushed. |
| 8 | `docs/SCHEMA_RULINGS.md` exists with all eight rulings verbatim | **DONE** | First file created in the repository. All eight present, unedited. |

**Four of eight complete.** The four outstanding are items 1, 3, 5 (the GitHub half)
and 7 — a single blocked chain: no GitHub push → no CI, no Railway deploy.

---

## 2. What was built

### Repository safety
`git init` ran **inside `app/`**. Confirmed `git rev-parse --show-toplevel` returns
`.../app`, and that the parent folder is not a repository. `state/customers.csv` is
outside the repository boundary and cannot be committed from it.

### Toolchain
`uv` 0.12.17, Python 3.12.14, Django 6.1.1, psycopg 3.3.6, Postgres 16.2.
Dependencies exactly as specified, plus nothing.

### Scaffold
`config` project, `ops` and `acct` apps — **both empty**, confirmed by
`makemigrations ops acct` reporting "No changes detected", and by a test that fails
if either ever gains a model while Slice 0 is the stated scope.

A third app, **`core`**, holds the platform infrastructure. See assumption A1.

### Database roles — a migration, not a manual step
`core/migrations/0002_database_roles.py` creates `ops_writer`, `acct_writer` and
`reporter`, and sets `ALTER DEFAULT PRIVILEGES` so future tables inherit the SELECT
floor. Prefix-specific write grants are applied by `manage.py apply_table_grants`,
which runs immediately after `migrate` in the pre-deploy command.

The `REVOKE UPDATE, DELETE` on the journal tables was **not** attempted. Those tables
do not exist. It is marked as a Slice B migration in `core/dbroles.py` and in
`docs/SCHEMA_RULINGS.md`.

### Seed quarantine — DATA_REVIEW §A1
* `DatasetSettings` singleton, `dataset_kind` defaulting to `SAMPLE`, created by data
  migration so a fresh database is quarantined from birth rather than from first page load.
* Context processor + base template + admin `base_site.html` override render
  **SAMPLE DATA — NOT ACTUALS** on every page. It fails *safe*: if the settings row
  cannot be read, it reports SAMPLE.
* `manage.py flip_dataset_to_actual --amount <TWD>` refuses, with `--amount` required
  and validated as exact decimal to 4 places. No plugged figures.

### Append-only audit log
Table + signal receivers + middleware recording who changed what and when.
**No customer PII**, structurally: the table records field *names*, never values, so
there is no column a buyer name or street address could land in. Append-only is
enforced by a Postgres trigger, not only by the model — verified by a test that
attempts raw SQL `UPDATE` and `DELETE` and asserts both are rejected.

### Tests — 45, all passing
Admin 200 for a logged-in superuser · banner rendering across five page types ·
migration forward-to-zero-and-back · roles and default privileges present · audit log
append-only and PII-free · flip command refuses · Slice 0 boundary held.

---

## 3. Backup and restore — item 4

```
dump     : ~/ledger-backups/local-2026-09-21-015111.sql.gz   (8.0K, gzipped, dated)
restored : into scratch database `restore_test`
tables   : 12
data     : dataset_kind=SAMPLE preserved; 1 user restored
ELAPSED  : 0.04 s
```

Scripts: `ops_scripts/backup.sh` (with a `--uat` mode for Railway) and
`ops_scripts/restore_test.sh`.

**Read that 0.04 s for what it is.** It is a restore of an empty schema with two rows
in it. It proves the dump is well-formed, the pipeline works end to end and the
tooling is correct. It tells you nothing about how long a restore will take once
there is a year of orders in there. Re-time it against `uat` after the first real
import, and again before cutover.

---

## 4. Secrets and PII — item 5

Verified **before** the first commit, not after:

* `git check-ignore` confirms `.env`, `.env.local`, `.env.production`, `.venv/`,
  `staticfiles/`, `db.sqlite3` and `.DS_Store` are all ignored.
* `.env.example` is explicitly un-ignored (`!.env.example`) and contains no secrets.
* The generated local secret key appears in `.env` and **nowhere else** — checked by
  grepping the staged tree and the whole working tree for the literal key.
* No `state/`, `customers.csv` or `orders.csv` path is tracked.
* CI has two guard steps that fail the build if `.env` or any customer data file
  is ever committed.

**Still unverified:** that these files are absent *from GitHub*. Nothing has been
pushed. That check happens after item 5's push and is yours to confirm with me.

---

## 5. The banner is a control, not a convention — item 6

Sabotaged three ways, each time running the suite, each time restoring:

| Sabotage | Result |
|---|---|
| Emptied `templates/includes/dataset_banner.html` | **6 of 12 tests failed** |
| Removed the context processor from `settings.py` | **6 of 12 tests failed** |
| Removed the banner from the admin override only | **4 of 12 tests failed** |
| Restored | **OK** |

A banner that can be removed without failing a test is not a control. This one cannot.

---

## 6. Assumptions made where the spec was silent

**A1 · A third Django app, `core`.**
You said build `ops` and `acct` and keep them EMPTY, and separately asked for a
settings model (item 6a) and an audit log table (item 7). Those are models, and they
had nowhere to go. Putting them in `ops` or `acct` would have violated the empty
rule and polluted a business namespace with platform tables. `core` keeps
`ops_*`/`acct_*` clean for the prefix grants. Alternative considered and rejected:
models in `config/`, which makes the project package an app.

**A2 · Roles are created without passwords.** Your item 5 says `CREATE ROLE ops_writer
LOGIN;`. KICKSTART §1 shows `PASSWORD '...'`. A password in a migration is a password
in Git, so the migration creates them password-less; they cannot connect until you set
one out of band. Nothing in Slice 0 connects as these roles.

**A3 · Reverse migration does not drop the roles.** A role is a cluster-wide object,
not a database object. A per-database migration that dropped it would remove it from
every other database in the cluster, and would fail anyway while it holds privileges
elsewhere. The reverse revokes the privileges granted in this database, which is the
full extent of what the forward migration granted.

**A4 · `ALTER DEFAULT PRIVILEGES` cannot filter by table prefix.** This is a Postgres
limitation, not a choice. It therefore carries only the SELECT floor, which is correct
for both readers. The prefix-specific write grants are applied by
`manage.py apply_table_grants`, which must run after any migration that creates
tables. It is wired into the pre-deploy command.

**A5 · Timezone `Asia/Taipei`.** The spec did not say. The business, its bookkeeping
and its close calendar are all in Taiwan, and a close calendar in UTC misdates entries
either side of midnight.

**A6 · A Dockerfile rather than Nixpacks auto-detection.** Makes the build identical
locally, in CI and on Railway. **Not verified — there is no Docker on this machine.**
Confirm on the first deploy.

**A7 · `/healthz` endpoint.** BUILD_TASK §4.2 asks for a healthcheck so a bad deploy
fails rather than serves errors. Added and wired into `railway.json`.

**A8 · The worker service is flagged, not created.** See §8.

**A9 · Test runner is Django's**, not pytest. You allowed either; Django's needs no
extra dependency.

**A10 · `auth.permission` rows are not audited.** They are created by `migrate`, not
by a person. Granting a permission *to a user* is recorded on the user row, which is
audited. Only the permission catalogue itself is skipped.

---

## 7. Things I did not do, and why

* **No business models.** No orders, inventory, lots, shipments, POs, journals,
  accounts or customers. No `state/coa.csv` load. No `ledger_event`,
  `acct_manual_entry` or posting logic. No Etsy importer. No notifications, charts or
  dashboards. No second Railway environment.
* **`COA_SPEC` §4.1 was read as context only.** No account table was built.
* **Nothing was written outside `app/`.** In particular `../RUNBOOK.md` was not
  edited, although KICKSTART §5 lists "the §0.3 rule is written in RUNBOOK.md" as a
  Slice 0 done-item. The rule is recorded in `docs/OPERATING_RULES.md` instead.
  **You need to copy it into `../RUNBOOK.md` yourself** — see §9.

---

## 8. Two points where I think the specs deserve a second look

Stated once, as required, and then dropped. Neither was acted on unilaterally.

**8.1 · The worker service has nothing to run in Slice 0.**
Your item 10 and BUILD_TASK §4.2 both specify web + worker + Postgres. The worker is
there for the importers and the posting engine — Slice A and Slice B. Neither exists.
A worker deployed now reads no queue, runs no task, and still bills against the $5
Hobby credit every hour, on a plan KICKSTART §0.3 already calls tight. I have written
the deploy docs for web + Postgres and flagged the worker as a Slice A item. **If you
want it created anyway, say so and I will add it** — it is your credit and your call.

**8.2 · One statement in the build instruction is factually out of date.**
Your brief says: *"The parent's .gitignore does not protect you: it ignores .env and
app/node_modules/, not state/."* The parent `.gitignore` as it stands today **does**
ignore `state/`, `inbox/` and `User Data Input/`, under an explicit "Customer PII and
business records — NEVER commit these" comment. Someone tightened it.

This changes nothing about what I did — the repository still belongs in `app/`, and
defence in depth is the right posture for customer addresses. I flag it only because
you may be carrying a stale mental model of what that file protects, and because
KICKSTART §3 Step 6a contains the same out-of-date sentence. I have not edited either
file.

---

## 9. What is outstanding, and what I need from you

In order. The first unblocks the rest.

**① Install Homebrew, then Postgres and the GitHub CLI.** *(needs your password)*
There is no Homebrew on this machine, so KICKSTART §2 Steps 1–2 never ran. I worked
around it with a user-space Postgres 16.2 for verification, **but that server lives in
a temporary directory and will disappear.** You need a real local Postgres.

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
eval "$(/opt/homebrew/bin/brew shellenv)"
brew install gh postgresql@16
brew services start postgresql@16
echo 'export PATH="/opt/homebrew/opt/postgresql@16/bin:$PATH"' >> ~/.zprofile
export PATH="/opt/homebrew/opt/postgresql@16/bin:$PATH"
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zprofile   # uv
createdb tattoo_ledger
```

Then, from `app/`: `uv run python manage.py migrate && uv run python manage.py
apply_table_grants && uv run python manage.py createsuperuser`.

**② `gh auth login`.** *(needs your browser)* GitHub.com → HTTPS → Yes → web browser.

**③ Tell me to push.** It creates a resource under your account, so I have not run it:
`gh repo create tattoo-ledger --private --source=. --push`. I will then confirm the
repo is private, confirm `.env` and `state/` are absent from GitHub, and watch CI.

**④ Tell me to set up Railway.** *(spends money — Hobby, $5/mo)* I have not touched
it. `docs/DEPLOY.md` has the full sequence. Decide on the worker first (§8.1).

**⑤ Copy the §0.3 rule into `../RUNBOOK.md`** — it is outside this repo and I was
scoped to `app/` only. The text is in `docs/OPERATING_RULES.md` §1.

---

## 10. Hours

| | |
|---|---|
| Automated build time this session | **≈ 0.7 h** (01:13 → 01:53) |
| Your time so far | ~0 h |
| Estimated remaining for items ①–⑤ | **1.5 – 2.5 h**, most of it waiting on Homebrew and Railway |
| **Slice 0 projected total** | **≈ 2.5 – 3 h** |
| Against the 40 h whole-build cap | **~3 h used, ~37 h left** |

BUILD_TASK §5 estimated Slice 0 at 8–10 hours. The estimate was for a person typing.
Do not read the saving as slack in the cap: Slices A and B are where the 40 hours
actually go, and their estimates assume the contracts in D1–D3 exist, which they do
not yet.
