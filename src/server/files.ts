import 'server-only';
import { open, link, unlink, mkdir, lstat } from 'node:fs/promises';
import { dirname } from 'node:path';
import { randomUUID } from 'node:crypto';

export async function assertNotSymlink(filename: string): Promise<void> {
  const info = await lstat(filename);
  if (info.isSymbolicLink()) throw new Error('Symbolic links are not allowed in the data store.');
}

export async function immutableWrite(filename: string, body: string | Buffer): Promise<void> {
  await mkdir(dirname(filename), { recursive: true, mode: 0o700 });
  const temporary = `${filename}.${randomUUID()}.tmp`;
  const handle = await open(temporary, 'wx', 0o600);
  try {
    await handle.writeFile(body);
    await handle.sync();
    await handle.chmod(0o400);
  } finally { await handle.close(); }
  try {
    await link(temporary, filename);
    const directory = await open(dirname(filename), 'r');
    try { await directory.sync(); } finally { await directory.close(); }
  } finally { await unlink(temporary); }
}
