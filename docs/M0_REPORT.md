# M0 foundation checkpoint — NOT ACCEPTED

**Subsequent founder decision, 2026-11-16:** M0 accepted and M1 authorised (“accept M0, psl proceed”). The historical test findings below are unchanged; acceptance does not turn blocked checks into passes. See `DECISIONS.md`.

**Dispatch date:** 2026-11-16, Asia/Hong_Kong. **Milestone status:** implemented foundation checkpoint; required runtime/browser acceptance remains blocked. **Do not advance to M1 or use this for actual books.**

## Authorisation and isolation

- D-W6 is treated as dispatched by the founder's packet, reversing D-W5. PROMPT_22 and PROMPT_17–19 are not being built.
- The packet simultaneously requests a root `DECISIONS.md` update and forbids writing outside `erp/`. The explicit read-only boundary wins. Dispatch is recorded in this report and `README.md`; the orchestrator must update the root decision log separately.
- All enumerated pre-flight references were opened successfully before creating `erp/`. Expected command, schema, and SAMPLE fixture families were present. No missing reference was waived.
- `erp/.gitignore` was the first authored file, before `git init` inside `erp/`. The TS guard and hook were created and wired before scaffolding. No root git repository, branch, or commit was created.
- No reference implementation writes, actual customer reads, inbox reads, cloud deployment, database, authentication provider, or notifications were performed. Runtime backup tools intentionally support the separately authorised `../erp-backups/` destination; validation used destinations inside `erp/` only.
- The reference snapshot covers 134 source/config/chart files. Their hashes and mtimes are checked for changes since inventory. A comprehensive pre-dispatch root-wide mtime baseline was not captured here; the orchestrator's independent mtime gate is still required.

## Implemented

- Strict TypeScript, Zod 4 schemas with inferred business types, isolated exact-decimal context, approved-chart account-code validation, and a type-aware money guard. Next is pinned to the stable registry version observed at dispatch, `16.4.6`; pnpm is pinned to `10.20.0`; the supported runtime is Node 22.
- Immutable, schema-validated runs, deterministic canonical hashes, replay validation, per-entry TWD balancing, transaction-currency triples, deposit-at-order checks, dispatch-date checks, and rejection of plug account names.
- No-overwrite atomic publication using a synced temporary file, hard link, and directory sync. A process mutex plus `proper-lockfile` serializes writers. No update/delete route exists.
- Exact reversing effects with original-run reference, second-reversal rejection, idempotency with cross-action collision protection, and a preview endpoint that writes zero runs.
- Closed-period rejection, structural five-distinct-PASS close checks, and founder-approval fields. **These are infrastructure safeguards, not computed G-1–G-5 parity. No close endpoint is exposed.**
- Quarantine checks requiring a reversed sample journal seed and posted founder-approved ACTUAL opening balances before activation. Reset refuses any ACTUAL record, even before activation; SAMPLE reset archives old history rather than deleting it.
- Integrity failure returns read-only status and the bad identifier. The shell contains the corresponding red banner. Error payloads do not echo input values. Customer effects stay out of the status cache and activity-table projection.
- Content-addressed evidence, private file modes, verified snapshot zip, independent zip checksum, per-file manifest, evidence hash verification, empty-target restore, and backup-age calculation including the seven-day boundary.
- Light-green responsive shell, collapsible navigation, persistent SAMPLE banner, period picker, setup guidance, honest pending-feature states, a searchable/sortable TanStack activity table with CSV export and a Radix record drawer, glossary, and four-step guided reversal UI.
- 41 synthetic CSVs, 15 header contracts, and the bilingual chart copied into `seed/`. Startup verifies and idempotently registers the fixture manifest; there is no runtime reference to `../app`.
- `PARITY.md` inventories 277 rows, including all 28 unique catalogue events, models, Python modules, management commands, gates, public report routes, migration obligations, recovery tools, and CSV contracts.

## Observed validation

The machine provides **Node 26.13.1**, not the authorised Node 22. Repeated registry/runtime downloads failed with timeouts and connection resets. A partial dependency tree was assembled from the existing local package cache for foundation-only validation; it is **not a successful clean `pnpm install`** and does not replace a lockfile or fresh-clone check. Ignored `.tools/` holds these temporary packages and logs.

| Check | Observed outcome |
|---|---|
| Vitest | **30 passed / 30**, six suites, on Node 26.13.1; rerun on Node 22 still required |
| Strict foundation typecheck | **PASS**, TypeScript 5.9.3, strict and `noUncheckedIndexedAccess`; domain, server, scripts, API-test imports, and process workers included |
| Standalone money guard | **PASS**; planted floating conversion and branded-money arithmetic are rejected by tests |
| Separate-process locking | **PASS**, four OS processes with the same key create one run |
| Crash publication | **PASS**, 20 actual SIGKILLs after a test-instrumented file handle writes half a temporary run; zero partial published JSON files, valid surviving history |
| Tamper / predecessor removal | **PASS**, read-only status names the affected run and rejects writes; browser rendering is not yet validated |
| API preview / duplicate / privacy | **PASS**, direct route-handler tests; preview zero writes, one reversal on retry, cross-origin rejection, no raw input in errors |
| Backup / restore | **PASS**, isolated synthetic round-trip, non-empty target rejection, corrupt zip rejection, corrupt evidence rejection, verified chain |
| SAMPLE fixture bytes | **PASS**, all 41 copied files match their recorded source hashes |
| Source guard content scan | **PASS** on authored/seed files; matched contents are not printed |
| Full `pnpm typecheck` | **BLOCKED/FAIL**, missing Next, form, table-core, and Playwright dependencies in the partial tree; not a clean UI typecheck |
| `pnpm lint` | **BLOCKED/FAIL**, incomplete ESLint plugin dependencies; standalone money guard is independently green |
| `pnpm build` | **REFUSED**, Node-version check correctly rejects Node 26 before Next starts |
| `pnpm e2e` | **BLOCKED/FAIL**, missing `playwright-core/lib/bootstrap`; no browser acceptance claimed |
| Fresh clone / canonical install | **NOT PASSED**, registry installation did not finish; no `pnpm-lock.yaml` was fabricated |
| First-commit guard gate | **PENDING**, no commit was authorised or created; empty `git ls-files` is not evidence of a successful staged-content audit |
| Financial parity tie-out | **NOT RUN**, see `PARITY_TIEOUT.md`; unknown differences are not zeros |

The crash test instruments the test worker's file handle, not production store code, to halt deterministically after half a real write. Parent-process signal assertions require SIGKILL. Stale lock timestamps are adjusted only in the isolated test workspace after the worker is dead; production history is never repaired.

## Parity disposition

- Safety guard and JSON recovery replacements are marked BUILT; PostgreSQL migrations and Django launch/config glue are DROPPED as technologies, not as accounting obligations.
- M1 master data/setup, M2 selling, M3 purchasing/stock, M4 accounting/posting/reporting, and M5 computed close/dashboard behavior remain explicitly DEFERRED. Their reasons and proposed routes are listed for founder review, not silently accepted as omissions.
- Full SAMPLE materialization is **not** complete: only the manifest is registered. No seed cash amount was invented, and no sample trial balance, stock valuation, or P&L is fabricated. Business importers must materialize the appropriate isolated sample scenario in their own milestones.
- Catalogue v1.9.4's Addendum J remains explicitly not built. D.1 remains the reference behavior until the stated first-real-statement and composition-evidence conditions are resolved.
- API payload and run schemas here cover foundation actions only. Full entity fields, FK-equivalent provenance checks, event economics, WAC, import headers/multiset digests, gate evidence calculations, and report provenance are still feature obligations.

## Important limitations

- A self-contained hash chain cannot detect a deleted final suffix or an attacker rewriting the complete chain. The local owner still controls the disk. Independently protected head anchoring and backups are the countermeasures; this implementation is tamper-evident, not tamper-proof.
- Regex checks cannot determine whether arbitrary prose names a real buyer, or inspect PII in binary images. The future Etsy/customer importer must segregate buyer fields and redact source attachments before enabling real uploads. There is no customer/upload API in M0.
- The status cache is deliberately minimal, not a completed operational projection engine. The Today queue currently provides real backup/setup guidance; business task computation and all financial charts are deferred. Metrics show missing data rather than guessed numbers.
- The seven-day reminder is based on the last successful local receipt. Deleting `.cache/` makes backup age unknown. Checksums do not encrypt backups.
- The browser shell, form behavior, visual responsiveness, and full lint/type/build output remain unaccepted until dependencies and the required runtime are available.

## Required next actions — still M0

1. Provide a working Node 22 installation and registry connectivity; keep the runtime/Next pins, do not silently downgrade.
2. Run a canonical `pnpm install`, generate and review the real lockfile, and verify the installed pre-commit hook in a fresh clone.
3. Run `pnpm typecheck`, `pnpm lint`, `pnpm test`, `pnpm build`, and `pnpm e2e` on Node 22; fix genuine source findings rather than declaring missing dependencies a pass.
4. Validate startup, red-banner read-only behavior, reset/recovery, and guided reversal in the real browser. Reconcile the M0 manifest-only seed boundary with the milestone's sample-materialization expectation.
5. Only then accept M0 and dispatch M1. Final RB and financial tie-out remain future gates; do not switch the founder's working books yet.

See `FILES_WRITTEN.md` for authored deliverables. There is no claim that M0 or the complete ERP rebuild is finished.
