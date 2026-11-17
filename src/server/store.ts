import 'server-only';
import { readFile, readdir, mkdir, chmod } from 'node:fs/promises';
import { join, relative } from 'node:path';
import { randomUUID } from 'node:crypto';
import lockfile from 'proper-lockfile';
import { Mutex } from 'async-mutex';
import writeFileAtomic from 'write-file-atomic';
import { canonical, digest } from '../domain/canonical';
import { DomainError } from '../domain/errors';
import { currentDataset, validateCandidate } from '../domain/invariants';
import { candidateSchema, metaSchema, runSchema, type Candidate, type Run } from '../domain/schemas';
import { assertNotSymlink, immutableWrite } from './files';

const mutexes = new Map<string, Mutex>();
const genesis = '0'.repeat(64);
export class IntegrityError extends DomainError {
  constructor(public readonly badRunId: string) { super('store', `Read-only: the history check failed at ${badRunId}. Restore a verified backup; do not repair history.`); }
}

export class RunStore {
  constructor(public readonly directory: string) {}

  async locked<Value>(operation: () => Promise<Value>): Promise<Value> {
    let mutex = mutexes.get(this.directory);
    if (!mutex) { mutex = new Mutex(); mutexes.set(this.directory, mutex); }
    return mutex.runExclusive(async () => {
      await mkdir(this.directory, { recursive: true, mode: 0o700 });
      await assertNotSymlink(this.directory);
      const release = await lockfile.lock(this.directory, { realpath: true, stale: 10000, update: 2000, retries: { retries: 100, minTimeout: 25, maxTimeout: 100 } });
      try { return await operation(); } finally { await release(); }
    });
  }

  async initialize(): Promise<void> {
    await this.locked(async () => {
      for (const part of ['runs', 'attachments', '.cache']) { await mkdir(join(this.directory, part), { recursive: true, mode: 0o700 }); await assertNotSymlink(join(this.directory, part)); }
      try { await readFile(join(this.directory, 'meta.json')); }
      catch (error) {
        if (!(error instanceof Error && 'code' in error && error.code === 'ENOENT')) throw error;
        if ((await this.runFiles()).length) throw new IntegrityError('metadata');
        await immutableWrite(join(this.directory, 'meta.json'), canonical(metaSchema.parse({ schemaVersion: 1, dataset: 'SAMPLE', createdAt: new Date().toISOString() })));
      }
      await this.readVerified();
    });
  }

  private async runFiles(directory = join(this.directory, 'runs')): Promise<string[]> {
    try { await assertNotSymlink(directory); } catch { throw new IntegrityError('run-directory'); }
    const entries = await readdir(directory, { withFileTypes: true });
    const files: string[] = [];
    for (const entry of entries.sort((left, right) => left.name.localeCompare(right.name))) {
      if (entry.isSymbolicLink()) throw new IntegrityError('unexpected-link');
      const filename = join(directory, entry.name);
      if (entry.isDirectory()) files.push(...await this.runFiles(filename));
      else if (entry.name.endsWith('.json')) files.push(filename);
      else if (!entry.name.endsWith('.tmp')) throw new IntegrityError('unexpected-file');
    }
    return files;
  }

  async readVerified(): Promise<Run[]> {
    try {
      await assertNotSymlink(join(this.directory, 'meta.json'));
      metaSchema.parse(JSON.parse(await readFile(join(this.directory, 'meta.json'), 'utf8')));
    } catch { throw new IntegrityError('metadata'); }
    const records: Run[] = [];
    for (const filename of await this.runFiles()) {
      const basename = filename.split('/').at(-1)?.replace(/\.json$/, '') ?? 'unknown';
      let record: Run;
      try {
        record = runSchema.parse(JSON.parse(await readFile(filename, 'utf8')));
        const { hash, ...body } = record;
        if (digest(body) !== hash || relative(join(this.directory, 'runs'), filename) !== `${record.createdAt.slice(0, 4)}/${record.createdAt.slice(5, 7)}/${record.runId}.json`) throw new Error();
      } catch { throw new IntegrityError(/^[a-f0-9-]{36}$/.test(basename) ? basename : 'invalid-filename'); }
      records.push(record);
    }
    const successors = new Map<string, Run>();
    for (const record of records) {
      if (successors.has(record.prevHash)) throw new IntegrityError(record.runId);
      successors.set(record.prevHash, record);
    }
    const ordered: Run[] = [], ids = new Set<string>(), keys = new Set<string>();
    let previous = genesis;
    while (successors.has(previous)) {
      const record = successors.get(previous)!;
      if (ids.has(record.runId) || keys.has(record.idempotencyKey)) throw new IntegrityError(record.runId);
      try { validateCandidate(candidateSchema.parse(recordToCandidate(record)), ordered); } catch { throw new IntegrityError(record.runId); }
      ordered.push(record); ids.add(record.runId); keys.add(record.idempotencyKey); successors.delete(previous); previous = record.hash;
    }
    if (successors.size) throw new IntegrityError(successors.values().next().value!.runId);
    return ordered;
  }

  async read(): Promise<Run[]> { return this.locked(() => this.readVerified()); }

  async execute(compute: (runs: readonly Run[]) => Candidate | Promise<Candidate>, preview = false): Promise<{ run: Run; duplicate: boolean; preview: boolean }> {
    return this.locked(async () => {
      const runs = await this.readVerified();
      const candidate = candidateSchema.parse(await compute(runs));
      const existing = runs.find((run) => run.idempotencyKey === candidate.idempotencyKey);
      if (existing) {
        if (existing.kind !== candidate.kind || existing.dataset !== candidate.dataset || existing.occurredOn !== candidate.occurredOn || canonical(existing.input) !== canonical(candidate.input)) throw new DomainError('idempotencyKey', 'This request key was already used for a different action. Reload the form.');
        return { run: existing, duplicate: true, preview };
      }
      validateCandidate(candidate, runs);
      const body = { ...candidate, runId: randomUUID(), createdAt: new Date().toISOString(), schemaVersion: 1 as const, prevHash: runs.at(-1)?.hash ?? genesis };
      const run = runSchema.parse({ ...body, hash: digest(body) });
      if (!preview) await immutableWrite(join(this.directory, 'runs', run.createdAt.slice(0, 4), run.createdAt.slice(5, 7), `${run.runId}.json`), canonical(run));
      return { run, duplicate: false, preview };
    });
  }

  async status() {
    return this.locked(async () => {
      try {
        const runs = await this.readVerified();
        const status = { dataset: currentDataset(runs), readOnly: false, badRunId: null as string | null, runCount: runs.length, lastHash: runs.at(-1)?.hash ?? genesis };
        await mkdir(join(this.directory, '.cache'), { recursive: true, mode: 0o700 });
        await assertNotSymlink(join(this.directory, '.cache'));
        await writeFileAtomic(join(this.directory, '.cache', 'status.json'), canonical(status), { mode: 0o600, fsync: true });
        return status;
      } catch (error) {
        if (!(error instanceof IntegrityError)) throw error;
        return { dataset: 'SAMPLE' as const, readOnly: true, badRunId: error.badRunId, runCount: null, lastHash: null };
      }
    });
  }

  async putAttachment(content: Buffer, extension: string): Promise<string> {
    if (!/^(csv|pdf|png|jpg|webp)$/.test(extension)) throw new DomainError('file', 'Use a CSV, PDF, or supported image.');
    if (content.byteLength > 20 * 1024 * 1024) throw new DomainError('file', 'Choose a file smaller than 20 MB.');
    const sha = (await import('node:crypto')).createHash('sha256').update(content).digest('hex');
    await this.locked(async () => {
      await this.readVerified();
      const filename = join(this.directory, 'attachments', `${sha}.${extension}`);
      try { await immutableWrite(filename, content); }
      catch (error) { if (!(error instanceof Error && 'code' in error && error.code === 'EEXIST')) throw error; }
      await chmod(filename, 0o400);
    });
    return sha;
  }
}

function recordToCandidate(record: Run): Candidate {
  return { kind: record.kind, occurredOn: record.occurredOn, dataset: record.dataset, input: record.input, effects: record.effects, idempotencyKey: record.idempotencyKey };
}
