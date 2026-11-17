import 'server-only';
import { backup } from '../src/server/archive';
import { store } from '../src/server/runtime';
try { console.log(`Backup saved: ${await backup(store)}`); }
catch { console.error('Backup failed. Keep the existing data and retry; no record was changed.'); process.exitCode = 1; }
