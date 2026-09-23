# Hardening 01 — public repository controls

**Date:** 2026-09-23

**Repository:** `SiMori92/Little-Spell---Retail-ERP` — public by founder decision

**Scope:** Slice 0 guard and documentation change only

## Pre-flight

Verified `.github/workflows/ci.yml`, `docs/SLICE_0_REPORT.md`, and
`../GATE_0_RESULT.md` exist. `git remote -v` points to
`https://github.com/SiMori92/Little-Spell---Retail-ERP.git` for fetch and push.
Nothing outside `app/` was edited.

## Changes

- `.githooks/pre-commit` is executable and calls `tools/repo_guard.py` against
  staged index paths and content, before Git creates a commit object.
- The guard rejects `.env` and `.env.*` except `.env.example`; private directory
  and business-data name markers; spreadsheet and CSV files except named CSV test
  fixtures; email-like content; and lines containing both a three-digit run and a
  street-type word. It prints the rule and path, never the matched content.
- `ALLOW_DATA_COMMIT=1` is documented in `README.md` and prints a warning naming
  each staged file and each overridden rule. CI ignores this local override.
- The two existing CI guards now run the shared path and content checks against
  all tracked files. The path guard also rejects `__pycache__/` and `.pyc` files.
  A separate CI step queries GitHub's API, prints current visibility and fails
  unless it equals the workflow's single `public` constant.
- `docs/OPERATING_RULES.md` and the top of `ops/tests.py` prohibit printing
  customer rows in public CI test failures. Tests must assert on IDs and counts.
- Row 5 of `docs/SLICE_0_REPORT.md` now preserves the old private-repo result as
  a superseded 2026-09-21 finding. It identifies the current public `SiMori92`
  source and the 2026-09-23 GitHub API check in place.
- Synthetic email values in three existing tests are assembled at runtime so
  the strict tracked-content guard does not need a test-file exemption.

## Verification

- Ran `git config core.hooksPath .githooks` in this checkout; the configured
  value is `.githooks`. The staged hook has executable mode `100755`.
- Seven isolated Git tests passed. A staged fake `customers.csv` made `git
  commit` fail with `sensitive-path` and no `HEAD`; the named fixture committed.
  Additional tests covered `.env.example`, pycache, staged email and address
  content, and the warning on the explicit override.
- The shared scanner passed against both staged files and the full tracked tree.
  `git diff --cached --check` passed.
- All 52 Django tests passed against local Postgres.
- GitHub API reported current repository visibility `public` and a complete
  `main` tree with no guarded data path; `.env.example` was the sole `.env*`
  path. The tree response was not truncated.

## Remaining limits

The hook is local to each clone until its one-line setup is run. Git also permits
`--no-verify` and the documented override. CI is a backstop after push; a failed
public CI run cannot retract an exposed commit. Content matching is an accident
barrier, not a proof that arbitrary content contains no private data. The live
Railway database, secret-key rotation, environment name, and Slice 0 deployment
gate remain separate outstanding work recorded in `SLICE_0_REPORT.md`.

No business model, importer, or posting logic was added.
