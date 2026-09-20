#!/usr/bin/env bash
#
# Restore a backup into a scratch local database and prove the tables are there.
# Times the restore, because "how long does it take" is the question you will be
# asking at the moment you least want to be measuring it.
#
# Usage: ops_scripts/restore_test.sh ~/ledger-backups/uat-2026-09-21-101500.sql.gz
#
set -euo pipefail

DUMP="${1:?usage: restore_test.sh <path-to-.sql.gz>}"
TARGET="${2:-restore_test}"

[[ -f "$DUMP" ]] || { echo "No such dump: $DUMP" >&2; exit 1; }

echo "Restoring $DUMP into database '$TARGET'"
dropdb --if-exists "$TARGET"
createdb "$TARGET"

# macOS `date` has no %N, so timing comes from python for sub-second precision.
START=$(python3 -c 'import time; print(time.time())')
gunzip -c "$DUMP" | psql --quiet --set ON_ERROR_STOP=on "$TARGET" > /dev/null
END=$(python3 -c 'import time; print(time.time())')
ELAPSED=$(python3 -c "print(f'{$END - $START:.2f}')")

echo
echo "Tables restored:"
psql "$TARGET" -c '\dt'

TABLE_COUNT=$(psql -tAc \
  "SELECT count(*) FROM pg_tables WHERE schemaname='public'" "$TARGET")
ROW_COUNT=$(psql -tAc \
  "SELECT count(*) FROM core_datasetsettings" "$TARGET" 2>/dev/null || echo 0)
USER_COUNT=$(psql -tAc "SELECT count(*) FROM auth_user" "$TARGET" 2>/dev/null || echo 0)
DATASET_KIND=$(psql -tAc \
  "SELECT dataset_kind FROM core_datasetsettings WHERE id=1" "$TARGET" 2>/dev/null || echo "?")

echo
echo "=================================================="
echo " RESTORE TEST RESULT"
echo "   source dump      : $DUMP"
echo "   target database  : $TARGET"
echo "   tables restored  : $TABLE_COUNT"
echo "   dataset settings : $ROW_COUNT row(s), dataset_kind=$DATASET_KIND"
echo "   users restored   : $USER_COUNT"
echo "   ELAPSED          : ${ELAPSED}s"
echo "=================================================="
echo
if [[ "$TABLE_COUNT" -lt 1 ]]; then
    echo "FAILED: the restored database has no tables." >&2
    exit 1
fi
echo "Write the elapsed time into docs/SLICE_0_REPORT.md."
