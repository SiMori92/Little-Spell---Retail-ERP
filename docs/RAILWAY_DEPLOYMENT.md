# Railway replacement deployment

The founder authorized replacing the Python build on the existing GitHub/Railway service with the latest Next.js build. This overrides the earlier local-only deployment boundary; the local `app/` remains frozen. The previous Python commit is retained in repository history and a rollback tag. No Django database or local runtime records are deleted or uploaded.

Railway's existing GitHub integration deploys `main` automatically; no Railway token is needed for the source push. Required volume/access configuration is still a service prerequisite, not something a Git push can provision. Native verification passed 123 unit/API/store tests, 22 browser flows, strict typecheck, lint/money guard, the production build, and hosted HTTP adapter checks for authentication, CSRF, restart persistence and ephemeral-startup refusal. The real Docker image, TLS edge and mounted Railway volume are verified by the automated deployment; they are not claimed from the native adapter smoke test alone.

## Runtime requirements

Deploy the repository root using `Dockerfile` and `railway.json`. The image uses Node 22, pnpm 10.20.0, the frozen lockfile and the production Next build. It starts with `pnpm start`; there are no Django migrations or Gunicorn commands. `/healthz` is the public, non-sensitive readiness endpoint.

Attach one persistent Railway volume at `/data`. Set `ERP_DATA_DIR=/data/erp`. The Railway config requires this mount; startup also checks the real Linux mount table and refuses ephemeral storage. Keep one replica and zero deployment overlap. A new empty volume initializes the SAMPLE workspace. Existing Python database records are not automatically migrated.

Set these service variables:

| Variable | Value |
|---|---|
| `ERP_DEPLOYMENT` | `railway` |
| `ERP_DATA_DIR` | `/data/erp` |
| `ERP_ACCESS_USERNAME` | `founder` or an explicit simple username |
| `ERP_ACCESS_PASSWORD` | A unique generated secret of at least 24 characters |
| `ERP_PUBLIC_ORIGIN` | The exact public HTTPS origin, without a path; may be omitted when Railway provides `RAILWAY_PUBLIC_DOMAIN` |

Railway supplies `PORT`, its volume mount metadata, and the generated public domain. Never commit access secrets. Retrieve the workspace password through the private Railway Variables interface. Requests to pages and API endpoints require HTTP Basic access over HTTPS; writes also require the configured same origin. The health endpoint exposes no record data. Local development stays bound to loopback and retains its original local-request checks.

The hosted proxy also disables indexing/caching and framing. The JSON store's atomic writes, locks, tamper checks and immutable run history remain in force. Hosted `pnpm backup` stores its checksummed zip under `/data/erp-backups`, outside the records directory but on the persistent volume; local backups retain `../erp-backups`. Copy backups off the service as well. Railway-volume snapshots and verified application backups are separate responsibilities; a persistent volume is not itself a backup.

## Rollback and verification

The deployment commit preserves the old `main` as an ancestor rather than force-pushing an unrelated history. The `python-before-nextjs-20261117` tag points to the prior Python build. Reverting the replacement commit restores that tree; restore its original service commands and database settings when rolling back. Do not remove the JSON volume or the old database during rollback.

Validate `/healthz`, unauthenticated 401 responses, signed-in pages, same-origin API preview/confirmation, persistent records across a restart, and the deployment's commit SHA. A successful deployment does not waive the financial-parity blockers in `PARITY_TIEOUT.md`.
