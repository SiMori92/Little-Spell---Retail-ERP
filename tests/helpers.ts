import { randomUUID } from 'node:crypto';
import { mkdir, mkdtemp, rm } from 'node:fs/promises';
import { resolve, join } from 'node:path';
import { RunStore } from '../src/server/store';
import { candidateSchema, type Candidate } from '../src/domain/schemas';

export async function workspace() {
  const root = resolve('.tools/test-workspaces');
  await mkdir(root, { recursive: true });
  const directory = await mkdtemp(join(root, 'store-'));
  const store = new RunStore(directory);
  await store.initialize();
  return { store, cleanup: () => rm(directory, { recursive: true, force: true }) };
}

export function journalCandidate(overrides: Partial<Candidate> = {}): Candidate {
  return candidateSchema.parse({
    kind:'journal.post', occurredOn:'2026-10-02', dataset:'SAMPLE', input:{ evidenceRef:'synthetic-evidence' }, idempotencyKey:randomUUID(),
    effects:[{ type:'journal.posted', opening:null, founderAuthorization:null, entry:{ entryId:randomUUID(), occurredOn:'2026-10-02', sourceEvent:'owner.funds_moved', lines:[
      { account:{ code:'1121', name:'Operating bank' }, debit:'1234.5000', credit:'0.0000', txnAmount:null, txnCurrency:null, fxRateId:null },
      { account:{ code:'3111', name:'Owner capital' }, debit:'0.0000', credit:'1234.5000', txnAmount:null, txnCurrency:null, fxRateId:null }
    ] } }], ...overrides
  });
}
