import 'server-only';
import { restore } from '../src/server/archive';
import { store } from '../src/server/runtime';
try {
  const archive = process.argv[2];
  if (!archive) throw new Error();
  await restore(archive, store.directory);
  console.log('Restore verified. Start Little Spell to rebuild projections.');
} catch { console.error('Restore refused. Supply a checksummed zip and an empty data directory.'); process.exitCode = 1; }
