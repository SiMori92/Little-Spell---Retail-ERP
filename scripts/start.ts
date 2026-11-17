import 'server-only';
import { spawn } from 'node:child_process';
import { checkNode } from './check-node';
import { initializeWorkspace } from '../src/server/initialize';
import { checkHostedStorage } from '../src/server/hosted-storage';
import { isHosted } from '../src/server/hosting';

checkNode();
await checkHostedStorage();
const status = await initializeWorkspace();
if (status.readOnly) console.error(`History verification failed at ${status.badRunId}. Starting in read-only mode.`);
const mode = process.argv[2] === 'start' ? 'start' : 'dev';
const child = spawn(process.execPath, ['node_modules/next/dist/bin/next', mode, '--hostname', isHosted()?'0.0.0.0':'127.0.0.1', '--port', process.env.PORT ?? '3000'], { stdio: 'inherit', env: process.env });
for (const signal of ['SIGINT', 'SIGTERM'] as const) process.on(signal, () => child.kill(signal));
child.on('exit', (code) => { process.exitCode = code ?? 1; });
