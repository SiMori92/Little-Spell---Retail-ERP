import 'server-only';
import { resolve } from 'node:path';
import { RunStore } from './store';
export const store = new RunStore(resolve(process.env.ERP_DATA_DIR ?? 'data'));
