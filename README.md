# Little Spell ERP v2 — M4/M5 checkpoint

Next.js / TypeScript ERP with local development and an explicitly configured private Railway deployment. Money, Close, Today and Reports are available; **the final financial parity/release gate has not passed**. The supplied Etsy settlement source is incomplete, and three discounted SAMPLE orders reveal a frozen-reference importer/posting mismatch. See `docs/PARITY_TIEOUT.md` before treating this as the actual books.

## Railway deployment

The repository root now deploys the Next.js build through `Dockerfile` and `railway.json`. Railway's GitHub integration deploys `main` automatically; no Railway token is needed for the Git push. The JSON store requires a persistent volume mounted at `/data`, one replica, and a configured private-access secret. Startup refuses missing persistent storage or access configuration. See `docs/RAILWAY_DEPLOYMENT.md`. The former Python build stays in Git history and the rollback tag; its database is not migrated or deleted.

## Current M4/M5 capabilities

- Money: guided expense/CSV intake and six manual fact types; save unposted, then separately review/post. Evidenced immutable public FX, exact Etsy placement/dispatch/fees/COGS, freight/duty evidence, clearing causes, and opposite-journal corrections.
- Stock costs post without subtracting dispatch quantities again. Old M3 journals retain their bytes; explicit reviewed metadata appends SKU/piece attribution. Stock shows posted vs pending costs and supports evidenced reorder policies.
- Close: computed G-1…G-5, missing-evidence states, WD+1 input review, WD+3 close attempts, founder authorization and effective-date period locks. A blocked attempt is saved and leaves the month OPEN. No all-green close is fabricated from incomplete SAMPLE evidence.
- Today: tasks derived from setup, selling, supplier documents, accounting queue, statement coverage, close diagnostics and backup age. Reports: 18 searchable/exportable report views, shared decimal-string KPI projections and six chart panels. Contribution is labeled MODELLED/ACTUAL with the NT$200 benchmark.
- Setup: guided seed retirement, separately evidenced real non-stock opening and one-way ACTUAL activation. Actual masters/stock remain separate from SAMPLE data. Activation is not a release-readiness certificate.
- Verification: 119 unit/API/store tests and 22 browser flows passed; typecheck, lint/money guard, production build and isolated production smoke passed. Three existing lint warnings and four existing tracing warnings remain. The independent G3 + synthetic manual-voucher comparison has zero differences and zero new runs on re-import; full Etsy/all-fixture parity is still blocked.

After `pnpm install`, use `pnpm dev` on `http://127.0.0.1:3000`. For production verification, run `pnpm build` then `pnpm smoke`; smoke uses fresh synthetic data and stops its own servers. Existing commands remain: `pnpm start`, `pnpm test`, `pnpm e2e`, `pnpm typecheck`, `pnpm lint`, `pnpm backup`, `pnpm restore <zip>`, `pnpm reset:sample`.

Startup still records the three idempotent SAMPLE manifest/master/Instagram runs. It does not silently approve source headers, invent stock or cash, post imported facts, or assume a bank settlement. General operational reversals/reprints/transit/late-cost workflows, nonzero packaging counts, complete report-format parity and audited period reopening remain explicit DEFERRED boundaries in `docs/PARITY.md`.

See `docs/M4_REPORT.md`, `docs/M5_REPORT.md`, `docs/SMOKE_REPORT.md`, and `docs/FILES_WRITTEN.md`. The earlier checkpoints below are historical descriptions of what was available at those milestones.

## M3 checkpoint

- `/buy`: purchase orders and immutable versions; good/damaged deliveries with evidenced short-close; supplier invoices; TWD operating-bank deposits, balances, refunds and forfeitures; exact CSV intake; document tables, lifecycle drawers, and visible matching exceptions.
- Sending a PO requires supplier/product compliance evidence. Sent prices, quantities, supplier and quote are frozen. One delivery and invoice per PO line is supported; omitting a line is not a deletion.
- A matching receipt/invoice pair posts a balanced receipt journal atomically with sellable stock. An unmatched document books no inventory or payable. Supplier-billed freight and non-creditable tax are allocated by value with the highest-line exact remainder. Damage carries its full landed cost, not a rounded per-piece reconstruction.
- Deposits are capped by PO value and precede any receipt. Their application is computed pro-rata, with the exact final remainder; supplier differences are listed, not plugged. Balance payments cannot exceed a matched invoice's remaining payable.
- `/stock`: complete evidenced opening counts and WAC decreases, explicit zero rows, damaged memos, dated on-hand/WAC, count history, and pending dispatch costs. Unknown quantities are not displayed as counted zero. M1 preparation is never silently posted.
- The original 74-row chart snapshot remains unchanged. First M3 activity appends the approved supplier-deposit account from the reference migration, bringing the adopted chart to 75 accounts without rewriting old runs.
- Packaging receipts are valued separately, outside sellable WAC; physical packaging counts remain zero-only in this reference scope. Carrier/duty/in-transit receipts, multi-delivery lines, late cost corrections and general procurement reversals remain unsupported.
- Operational WAC consumes existing M2 shipments once and labels COGS unposted. M4 must post that cost without deducting pieces again; operational stock is not a completed GL tie-out.
- Preview before confirmation: matched receipts, payments and actual counts book their displayed balanced journal, as the reference does. Manual accounting entries and general selling posting remain M4.
- Startup still creates only the three SAMPLE manifest/master/Instagram runs. It never invents opening stock, bank funds or supplier documents. See `docs/M3_REPORT.md`; stop here for founder review before M4.

## M2 checkpoint

- `/sell`: guided Etsy pair import, Instagram CSV/manual deals, table and kanban views, immutable status history, monthly statement controls, the UNPOSTED accounting queue, and guided Etsy dispatch.
- The source Etsy headers remain explicitly unverified. A preview cannot bypass that gate. A founder may record an evidenced review of the exact ordered headers/fingerprints for the current dataset before confirming an import.
- Each discounted coupon needs one evidenced, date-valid funding rule. No funding, exchange rate, stock, cost, or bank reconciliation is guessed. Changes to a booked order or statement multiset are refused; repeat imports write zero new runs.
- Buyer/contact columns, descriptions, and statement narratives are discarded before persistence. Original source files are not retained. Keep originals privately outside this application. No customer notification is sent.
- Instagram payment/shipping states remain pipeline facts, not proven cash or stock movements. ACTUAL paid states remain blocked until wallet evidence is implemented. Etsy dispatch consumes only previously counted sellable pieces; M1 preparation is not stock.
- Startup registers the fixture manifest, loads sample masters, and imports the authored SAMPLE Instagram pipeline: three runs in a fresh workspace. Etsy fixture booking stays gated by founder header review and counted stock. Tests provide synthetic stock independently; normal startup never invents it.
- Placement emits a deposit event, never revenue. Dispatch emits separate revenue and COGS events dated at dispatch. Events remain UNPOSTED until M4 review; the tested pure placement/dispatch journal functions do not book anything automatically.
- Today shows derived orders-to-ship, due follow-ups, and header-review tasks. Financial KPIs remain unavailable rather than fabricated.
- See `docs/M2_REPORT.md` for the historical checkpoint. The founder subsequently authorized M3.

## M1 checkpoint

- `/setup`: business details, supplier/product additions, evidenced compliance revisions, two fixed sales channels, and the 74-account bilingual approved chart.
- Every action uses Enter → Check → Preview → Confirm. Previews do not write; confirmations create immutable runs. Supplier identity and product identity/conversion are fixed after creation.
- Supplier v1 and product v3 CSV headers match the reference. Channels/accounts have explicit v2-authored v1 contracts. Imports enforce dated filenames, dataset provenance, and idempotency. Supplier imports must include every existing supplier.
- Every master list supports search, filtering, sorting, record details, and current-view CSV export. Supplier/product drawers include evidence-backed change histories.
- M1 introduced synthetic master fixtures and reference data, alongside the M0 fixture manifest. M2 additionally materializes the authored Instagram pipeline; purchasing, stock, and financial fixture materialization remain future work.
- Opening stock is a preparation or an explicit no-stock declaration, **not inventory or a journal**. A nonzero preparation stays pending until M3 posts it. Completed setup declarations do not establish financial readiness.
- See `docs/M1_REPORT.md` for historical verification and carry-forward gates. The founder subsequently authorized M2.

## Run

Select Node 22 (`nvm use`), enable Corepack (`corepack enable`), then:

```sh
pnpm install
pnpm dev
```

Open `http://127.0.0.1:3000`. Startup checks Node, creates the ignored data store, verifies the immutable run chain, registers the bundled synthetic-fixture manifest idempotently, rebuilds the safe status projection, then starts Next bound to loopback. No source outside this repository is needed at runtime. Broken history starts read-only with the affected identifier; it is never repaired automatically.

The bundled 41 SAMPLE CSVs are preserved for milestone importers. **Current startup materializes masters and the Instagram pipeline, not stock or accounting balances.** There are no invented financial KPIs, no unverified green close gates, and no fake parity tie-out. Pending flows remain visibly unavailable.

## Commands

| Command | Purpose |
|---|---|
| `pnpm dev` | Initialize and run the local development workspace |
| `pnpm build` / `pnpm start` | Build, then initialize and run locally in production mode |
| `pnpm test` | Domain, store, cross-process, crash, guard, recovery and API tests |
| `pnpm e2e` | Guided M0 browser flows in an isolated synthetic workspace |
| `pnpm typecheck` / `pnpm lint` | Strict types, framework lint, and type-aware money guard |
| `pnpm guard` | Inspect staged paths and contents, fail closed |
| `pnpm backup` | Verified snapshot zip plus checksum in `../erp-backups/` |
| `pnpm restore /absolute/path/backup.zip` | Restore only into empty `data/`, verify every checksum and chain |
| `pnpm reset:sample` | Archive existing SAMPLE history beside `data/`, seed a fresh workspace; refuses any ACTUAL record |

Playwright needs its browser installed once: `pnpm exec playwright install chromium`. `zip` and `unzip` must be on PATH for backup/restore (included on macOS). Backup commands intentionally write to the founder-requested directory outside this git repository. Building M0 does not execute that external write.

## Safety boundaries

- Runs are the only business authority. `meta.json` is immutable genesis metadata; the current dataset is replayed from activation runs, not changed in a second write. `.cache/` is disposable and contains status metadata only, never customer search data.
- All writes validate the complete candidate and per-entry TWD balance before atomically publishing one file. A process mutex and an OS-visible lockfile serialize writers. Publication uses a synced temporary file, no-overwrite hard link, and directory sync. Interrupted `.tmp` files are ignored, not treated as runs or silently repaired.
- There is no update/delete API. Guided reversal computes exact opposite stock and journal effects. Preview writes nothing. Closed-month, provenance, duplicate identifier, and quarantine checks are revalidated on replay.
- Generic infrastructure supports evidenced close effects, but it does **not** compute G-1–G-5; no close endpoint is exposed. A string saying PASS is not accounting evidence. Exact gates are an M5 obligation.
- Only `customer.*` runs may carry customer fields. No customer API/importer exists yet. Error responses never echo submitted values; cache and activity-table DTOs omit customer records. Human names in arbitrary prose cannot be reliably detected by a regex; feature schemas must keep buyer fields segregated when built.
- A local owner can alter disk files. Hash chaining detects corruption and missing predecessors, not deletion of the complete tail or an adversary recomputing every hash. Strong rollback detection needs a separately protected head anchor; a verified independent backup is essential. This is tamper-evidence, not tamper-proof storage.
- Local disks can fail, and a checksum does not encrypt data. Store backups privately. The seven-day reminder reflects the last successful local backup receipt; deleting the cache makes backup age unknown rather than inventing a recent backup.
- The hook scans staged blobs and rejects data, credentials, and email/address patterns without printing matched contents. It has no bypass. `prepare` wires it after clone/install. No first commit is created automatically.

## Build decisions and scope

D-W6 was dispatched by this packet on **2026-11-16 (Asia/Hong_Kong)**, reversing D-W5 and superseding PROMPT_22 / PROMPT_17–19 for this rebuild. The reference `app/` remains frozen. The packet both asks for `DECISIONS.md` to be updated and forbids editing it; the narrower explicit write boundary wins. This dispatch is recorded here instead; the orchestrator must update the root decision log separately.

See `docs/PARITY.md` for the inventory and milestone allocations, the M0–M2 reports for historical findings, `docs/M3_REPORT.md` for current verification, and `docs/PARITY_TIEOUT.md` for the explicitly unrun financial tie-out. Do not advance a deferred business flow into actual use without its tests and reference-output comparison.
