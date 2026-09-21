#!/usr/bin/env bash
#
# Take a gzipped, dated pg_dump to ~/ledger-backups.
#
# Usage:
#   ops_scripts/backup.sh                 # dumps $DATABASE_URL from app/.env
#   ops_scripts/backup.sh --uat           # dumps the Railway uat database via `railway run`
#   DATABASE_URL=... ops_scripts/backup.sh
#
# BUILD_TASK §4.4: Railway's managed backups are one provider's copy in one place.
# For books that is not a backup. This script is the second copy.
#
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-$HOME/ledger-backups}"
STAMP="$(date +%F-%H%M%S)"
mkdir -p "$BACKUP_DIR"

if [[ "${1:-}" == "--uat" ]]; then
    LABEL="uat"
    OUT="$BACKUP_DIR/${LABEL}-${STAMP}.sql.gz"
    echo "Dumping Railway uat -> $OUT"
    # The URL is never printed or written to a file; railway injects it into the
    # subprocess environment only.
    railway run bash -c 'pg_dump --no-owner --no-privileges "$DATABASE_URL"' | gzip > "$OUT"
else
    LABEL="local"
    if [[ -z "${DATABASE_URL:-}" ]]; then
        SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
        # shellcheck disable=SC1091
        set -a; source "$SCRIPT_DIR/../.env"; set +a
    fi
    OUT="$BACKUP_DIR/${LABEL}-${STAMP}.sql.gz"
    echo "Dumping local -> $OUT"
    pg_dump --no-owner --no-privileges "$DATABASE_URL" | gzip > "$OUT"
fi

SIZE="$(du -h "$OUT" | cut -f1)"
echo "Wrote $OUT ($SIZE)"
echo
echo "A backup you have not restored is a belief, not a control. Verify it:"
echo "  ops_scripts/restore_test.sh \"$OUT\""
