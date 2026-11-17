# M1 — Masters and guided setup

Date: 2026-11-16 (Asia/Hong_Kong). The founder accepted M0 and authorized M1. This is the M1 implementation checkpoint, not permission to use v2 for real books. Stop here for founder review before M2.

## Delivered

- Shared strict Zod schemas for supplier, product, channel, full chart account, business details, opening preparation, API payloads, master effects, and replay projections. Existing M0 imports retain the shared primitive schemas.
- Supplier and product forms with four steps: Enter → Check → Preview → Confirm. Previews write nothing; confirmations append one validated atomic run. No booked-record update or delete routes exist.
- Evidenced supplier compliance/payment-term revisions and product ingredient-evidence revisions. Immutable identity fields cannot be changed. Optimistic version and preview-head checks refuse stale confirmation.
- Supplier/product drawers show immutable version histories and field-level evidence, including prior values. All master tables provide search, status filters, sorting, current-view CSV exports, and record details.
- Exact supplier v1 and product v3 CSV headers, bounded quoted/BOM/multiline CSV parsing, verified-contract checks, dated filenames, dataset quarantine, foreign-key-equivalent supplier checks, full supplier snapshots, and formula-safe exports. Obsolete product headers are rejected, not guessed.
- Fixed Etsy/Instagram channels and the unchanged 74-account bilingual approved chart. Their CSV contracts are explicitly authored for v2; arbitrary channels/chart changes are refused.
- SAMPLE startup now records two runs: the original fixture manifest plus an atomic master bootstrap. It materializes the supplier/product sample fixtures, official accounts, and channels. It does not invent financial seed amounts or import unrelated fixtures.
- Persistent setup checklist, business details, a stock-preparation/no-stock declaration flow, and a Today task derived from current setup records. Financial metrics remain visibly unavailable.
- A real pnpm lockfile, successful canonical installation, and local Node 22.23.5 validation. The installed stack pins were retained.

## Opening-stock boundary — founder review required

Opening preparation is not booked stock. A nonzero preparation records evidenced quantities and exact per-piece costs but creates no inventory move or journal; the checklist says “Prepared · posting pending in M3.” An explicitly confirmed no-stock declaration can complete setup declarations, but the page still states that opening balances and financial readiness are not certified.

Actual opening-stock posting and count CSV intake remain M3/M4 work. This is an explicit deferral from the full first-run wizard requirement, not a claim that inventory opening is finished. The founder may accept or reject this allocation.

## Observed verification

| Check | Result |
|---|---|
| Canonical pnpm install | PASS; real lockfile generated; pnpm 10.20.0 |
| Node runtime | Node 22.23.5 for all checks |
| Typecheck | PASS; full project, no errors |
| Lint and money guard | PASS; zero errors, three warnings |
| Vitest | PASS; 45 tests across 8 files |
| Playwright Chromium | PASS; 7 tests, including the two foundation flows and narrow-screen setup |
| Production build | PASS; four dynamic-filesystem tracing warnings |
| Production startup | PASS on loopback; two SAMPLE runs, 3 suppliers, 12 products, 2 channels, 74 accounts; preview creates no run; mobile setup fits |
| Reference integrity comparison | All 134 files in the preserved M0 reference snapshot have identical SHA256 and mtime |
| Source guard scan | All nonignored authored files scanned directly, including untracked files; no PII/credential/path findings |
| Hook | `.githooks/pre-commit` is executable and configured as `core.hooksPath` |

The lint warnings are one existing anonymous PostCSS export and React-Compiler/TanStack compatibility notices on the two table components. No lint rule was disabled. Build tracing warnings reflect local filesystem paths; build artifacts remain private and git-ignored. This is a local-only application, not a cloud deployment package.

Vitest covers exact decimal preparation totals, stale previews, immutable identity fields, evidenced change logs, frozen accounts, CSV validation/duplicates, provenance, closed periods, privacy refusal, and replay effect forgery. Existing store tests still cover hash tampering, atomicity, twenty interrupted writes, process locking, recovery, and planted unsafe money conversion.

Playwright covers inline validation; business preview with unchanged run count; supplier/product additions and evidenced revisions; all four master CSV imports and duplicate confirmations; filtered export; bilingual accounts/channels; preparation without journal/move effects; explicit no-stock confirmation; computed Today guidance; mobile width; and the earlier reversal/quarantine flows. The browser suite uses an isolated synthetic workspace. Its default port is 3217, overridable with `ERP_E2E_PORT`; an unrelated process on 3100 was left untouched.

## Defects caught and fixed during review

1. Planner input and effects shared object references, allowing an effect mutation to mutate its own validation source. They are now independently cloned; the forged-effect/rehashed-run regressions pass.
2. Real Next requests rewrite the internal loopback URL hostname. Origin checking now uses a strictly validated incoming loopback Host with the same port; nonlocal hosts, cross-origin requests, and port mismatches remain blocked.
3. The top action controls overflowed a narrow viewport. They now wrap inside the available width; the 390-pixel browser assertion passes.

## Parity rows closed

Thirteen reference rows become BUILT: Supplier, Product, SupplierChange, ProductComplianceChange, Channel, Account, supplier/product intake functions, their two command replacements, supplier v1/product v3 headers, and the chart snapshot. Product v1/v2 headers are DROPPED with the explicit obsolete-header reason. Mixed modules remain DEFERRED for their unbuilt behavior; procurement/invoice/payment rows are corrected to M3 rather than incorrectly claiming master coverage satisfies them.

## Carry-forward gates and limitations

- M2–M5, complete SAMPLE fixture materialization, accounting catalogue examples, computed close checks, dashboard charts, and the financial tie-out are not built. `PARITY_TIEOUT.md` stays NOT RUN; no zero difference is claimed.
- The current reference ACTUAL-flip command requires a separate empty actual environment, while the rebuild packet/M0 domain requires sample-seed reversal plus approved real opening. M1 exposes no activation endpoint. Resolve that reference/packet discrepancy explicitly before enabling ACTUAL; M1 does not silently change the accepted foundation.
- Source patterns can refuse contact details, but cannot reliably classify arbitrary human names. No customer import or notification capability is exposed. Master CSVs must not contain buyer data.
- The repository still has no commit or staged files. The direct guard scan is meaningful; an empty `git ls-files` is not evidence of a safe first commit. First-commit ordering, a true fresh-clone install on the founder's machine, and full root-wide mtime gate remain orchestrator checks.
- Backup/recovery tests use isolated destinations within the ignored test workspace. No real backup outside `erp/` was created during this build; `pnpm backup` intentionally targets the founder-requested sibling directory when invoked later.
- No file outside `erp/` was authored, and neither the frozen Django app nor actual customer/inbox data was modified or opened. The 134-reference snapshot comparison is narrower than the orchestrator's complete root-wide mtime gate.

See `FILES_WRITTEN.md` for the complete authored-file inventory. Historical M0 blocked checks remain in their original report; successful follow-up checks here do not rewrite that history.
