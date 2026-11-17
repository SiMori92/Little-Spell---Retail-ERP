import 'server-only';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { readFile, writeFile, mkdir, mkdtemp, readdir, rm, rename, lstat, chmod } from 'node:fs/promises';
import { join, resolve, dirname, relative } from 'node:path';
import { createHash, randomUUID } from 'node:crypto';
import { z } from 'zod';
import writeFileAtomic from 'write-file-atomic';
import { RunStore } from './store';
import { assertNotSymlink } from './files';
import { DomainError } from '../domain/errors';
import { hostedEnvironment,isHosted } from './hosting';

const exec = promisify(execFile);
const sha = (body: Buffer) => createHash('sha256').update(body).digest('hex');
const receiptSchema = z.strictObject({ createdAt: z.iso.datetime(), sha256: z.string().regex(/^[a-f0-9]{64}$/), name: z.string().regex(/^[a-zA-Z0-9_.-]+\.zip$/) });
const manifestSchema = z.record(z.string(), z.string().regex(/^[a-f0-9]{64}$/));
const safeEntry = (name: string) => name === 'meta.json' || /^runs\/\d{4}\/\d{2}\/[a-f0-9-]{36}\.json$/.test(name) || /^attachments\/[a-f0-9]{64}\.(csv|pdf|png|jpg|webp)$/.test(name);

async function filesUnder(directory: string, root = directory): Promise<string[]> {
  const files: string[] = [];
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    if (entry.name === '.cache' || entry.name.endsWith('.tmp')) continue;
    if (entry.isSymbolicLink()) throw new DomainError('backup', 'Remove symbolic links before backing up.');
    const filename = join(directory, entry.name);
    if (entry.isDirectory()) files.push(...await filesUnder(filename, root));
    else files.push(relative(root, filename));
  }
  return files.sort();
}

export async function backup(store: RunStore, destination = isHosted()?join(hostedEnvironment().RAILWAY_VOLUME_MOUNT_PATH,'erp-backups'):resolve('../erp-backups')): Promise<string> {
  return store.locked(async () => {
    await store.readVerified();
    const stagingRoot = resolve('backups');
    await mkdir(stagingRoot, { recursive: true, mode: 0o700 });
    const staging = await mkdtemp(join(stagingRoot, 'snapshot-'));
    const manifest: Record<string, string> = {};
    await mkdir(destination, { recursive: true, mode: 0o700 });
    await assertNotSymlink(destination);
    const createdAt = new Date().toISOString();
    const archive = join(destination, `little-spell-${createdAt.replace(/[:.]/g, '-')}-${randomUUID()}.zip`);
    try {
      for (const name of await filesUnder(store.directory)) {
        if (!safeEntry(name)) throw new DomainError('backup', 'The data directory contains an unexpected file.');
        const content = await readFile(join(store.directory, name));
        if (name.startsWith('attachments/') && name.split('/')[1]?.split('.')[0] !== sha(content)) throw new DomainError('backup', 'An evidence file failed verification. No successful backup was recorded.');
        manifest[name] = sha(content);
        const target = join(staging, name);
        await mkdir(dirname(target), { recursive: true, mode: 0o700 });
        await writeFile(target, content, { flag: 'wx', mode: 0o600 });
      }
      await writeFile(join(staging, 'manifest.json'), JSON.stringify(manifest), { flag: 'wx', mode: 0o600 });
      await exec('zip', ['-q', '-r', archive, '.'], { cwd: staging });
      await chmod(archive, 0o600);
      const checksum = sha(await readFile(archive));
      await writeFile(`${archive}.sha256`, `${checksum}\n`, { flag: 'wx', mode: 0o600 });
      await mkdir(join(store.directory, '.cache'), { recursive: true, mode: 0o700 });
      await writeFileAtomic(join(store.directory, '.cache', 'backup.json'), JSON.stringify({ createdAt, sha256: checksum, name: archive.split('/').at(-1) }), { mode: 0o600, fsync: true });
      return archive;
    } finally { await rm(staging, { recursive: true, force: true }); }
  });
}

export async function restore(archive: string, target: string): Promise<void> {
  const absolute = resolve(archive);
  const checksum = (await readFile(`${absolute}.sha256`, 'utf8')).trim();
  if (!/^[a-f0-9]{64}$/.test(checksum) || sha(await readFile(absolute)) !== checksum) throw new DomainError('backup', 'The backup checksum does not match. Nothing was restored.');
  const list = (await exec('unzip', ['-Z1', absolute], { maxBuffer: 1024 * 1024 })).stdout.split('\n').filter((name) => name && !name.endsWith('/'));
  if (new Set(list).size !== list.length || !list.includes('manifest.json') || list.some((name) => name !== 'manifest.json' && !safeEntry(name))) throw new DomainError('backup', 'This archive contains unsafe or unexpected paths.');
  const readEntry = async (name: string) => (await exec('unzip', ['-p', absolute, name], { encoding: 'buffer', maxBuffer: 64 * 1024 * 1024 })).stdout;
  const manifest = manifestSchema.parse(JSON.parse((await readEntry('manifest.json')).toString('utf8')));
  if (!manifest['meta.json'] || Object.keys(manifest).some((name) => !safeEntry(name)) || list.length !== Object.keys(manifest).length + 1 || Object.keys(manifest).some((name) => !list.includes(name))) throw new DomainError('backup', 'The backup file list does not match its manifest.');
  const targetStore = new RunStore(resolve(target));
  await targetStore.locked(async () => {
    if ((await readdir(targetStore.directory)).length) throw new DomainError('backup', 'Restore needs an empty data directory. Existing records were not changed.');
    const staging = await mkdtemp(`${targetStore.directory}.restore-`);
    try {
      let total = 0;
      for (const [name, checksum] of Object.entries(manifest)) {
        const content = await readEntry(name);
        total += content.byteLength;
        if (total > 512 * 1024 * 1024 || sha(content) !== checksum) throw new DomainError('backup', 'A backup file failed verification. Nothing was restored.');
        if (name.startsWith('attachments/') && name.split('/')[1]?.split('.')[0] !== sha(content)) throw new DomainError('backup', 'An evidence file failed verification.');
        const filename = join(staging, name);
        await mkdir(dirname(filename), { recursive: true, mode: 0o700 });
        await writeFile(filename, content, { flag: 'wx', mode: 0o400 });
      }
      await mkdir(join(staging, 'runs'), { recursive: true, mode: 0o700 });
      await mkdir(join(staging, 'attachments'), { recursive: true, mode: 0o700 });
      await new RunStore(staging).readVerified();
      await rename(staging, targetStore.directory);
    } finally { await rm(staging, { recursive: true, force: true }); }
  });
}

export async function lastBackup(directory: string): Promise<{ days: number | null; stale: boolean }> {
  try {
    const receipt = receiptSchema.parse(JSON.parse(await readFile(join(directory, '.cache', 'backup.json'), 'utf8')));
    const age = Math.max(0, Date.now() - Date.parse(receipt.createdAt));
    const days = Math.floor(age / 86400000);
    return { days, stale: age > 7 * 86400000 };
  } catch { return { days: null, stale: true }; }
}

export async function resetSample(store: RunStore): Promise<string> {
  return store.locked(async () => {
    const runs = await store.readVerified();
    if (runs.some((run) => run.dataset === 'ACTUAL' || run.kind === 'dataset.activate')) throw new DomainError('dataset', 'Actual data can never be reset. Use reversing entries.');
    const archived = `${store.directory}.sample-archive-${randomUUID()}`;
    await rename(store.directory, archived);
    await mkdir(store.directory, { mode: 0o700 });
    if (!(await lstat(archived)).isDirectory()) throw new DomainError('dataset', 'The sample archive could not be verified.');
    return archived;
  });
}
