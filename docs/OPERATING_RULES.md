# Operating rules established in Slice 0

## 1. No real data until a second environment exists

KICKSTART §0.3.

> No real customer or order data enters the `uat` environment until a second
> environment exists.

One environment is the financially correct call on Hobby, and with zero orders there
is only synthetic data to protect. But the day the first real Etsy export is
imported, `uat` silently becomes production — and a single-environment production
with `main` auto-deploying migrations is how you lose your books.

**This rule is also required in `../RUNBOOK.md`,** which is outside this repository.
Slice 0 did not edit it, because writing outside `app/` was out of scope for this
build. Copy it across by hand.

## 2. The sample seed is quarantined until a real opening entry exists

DATA_REVIEW addendum §A1. `dataset_kind` starts at `SAMPLE`; every page carries the
banner; `flip_dataset_to_actual` refuses until the seed JE is reversed and a real,
founder-signed opening entry is posted. No plugged figures, under any label.

## 3. Corrections to the books are reversing entries

Never an UPDATE, never a DELETE. The `REVOKE UPDATE, DELETE` that enforces it is a
**Slice B** migration — the journal tables do not exist yet. Recorded in
`SCHEMA_RULINGS.md` so it is not lost between slices.

## 4. Migrations run in the pre-deploy slot

Never in the container entrypoint. A failed migration must fail the deploy, not
crash-loop a half-migrated app.

## 5. Nothing above `app/` is tracked by git

`state/` holds customer names and addresses. CI fails the build if a `state/` or
customer data file ever appears in the repository.

## 6. Test output is public

GitHub Actions logs for this public repository can be read by anyone. Tests must
never print a row of customer data on failure. Assert on identifiers and counts,
never on a rendered customer row. This applies to future Slice A importer tests as
well as any later test that touches real records.
