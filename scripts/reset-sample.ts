import 'server-only';
import { resetSample } from '../src/server/archive';
import { store } from '../src/server/runtime';
import { initializeWorkspace } from '../src/server/initialize';
try { await resetSample(store); await initializeWorkspace(); console.log('Sample workspace reset. The old sample history is retained beside data/.'); }
catch { console.error('Reset refused. Actual data or unverified history cannot be reset.'); process.exitCode = 1; }
