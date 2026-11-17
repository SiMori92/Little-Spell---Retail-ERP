# Production smoke — PASS

Executed 2026-11-17 using Node 22.23.5, pnpm 10.20.0 and the production build on loopback ports 3245/3246. Every record was synthetic, in a new ignored `.tools/smoke/` workspace. Both owned test servers were stopped afterward. The founder's `data/` was not used.

| Check | Observed result |
|---|---|
| Fresh startup | Three initial SAMPLE runs; quarantine banner visible |
| Guided funding | Saved UNPOSTED; no journal created by the form submission |
| Separate posting | Exact 1000.0000 TWD entry, reviewed separately |
| Preview | Zero new runs |
| Duplicate confirmation | Same run returned; zero new runs |
| Guided correction | Opposite journal recorded; original retained |
| Guided expense | Receipt fact recorded through four steps |
| Close attempt | Missing evidence remains NOT_RUNNABLE; blocked attempt leaves month OPEN |
| Report API | All 18 reports available; G-2 remains NOT_RUNNABLE |
| Page sweep | Today, Sell, Buy, Stock, Money, Close, Reports, Setup and dataset transition render |
| Mobile | Today, Money, Close and Reports fit a 390-pixel viewport |
| Backup / restore | Checksummed zip restored into an empty isolated directory; verified run count identical |
| Tamper restart | Changed one hash byte in a copied store; read-only banner names the first bad run and disables recording |
| Browser errors | Zero page errors |

Repeat after `pnpm build` with `pnpm smoke`. The smoke script keeps backups inside its synthetic workspace so it does not write outside `erp/`; normal `pnpm backup` retains the specified external destination. Machine-readable smoke results and execution logs are ignored under `.tools/`.

This smoke covers operational software behavior. It does not certify full financial parity, missing settlement composition, a successful financial close, ACTUAL activation on founder data, or the final fresh-clone/first-commit/root-wide audit gates. See `PARITY_TIEOUT.md`.
