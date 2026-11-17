import { afterEach, describe, expect, test } from 'vitest';
import { readFile, writeFile, chmod, readdir, rm } from 'node:fs/promises';
import { join } from 'node:path';
import { randomUUID } from 'node:crypto';
import { canonical } from '../src/domain/canonical';
import { candidateSchema, journalSchema, type Candidate } from '../src/domain/schemas';
import { planReversal } from '../src/domain/reversal';
import { workspace, journalCandidate } from './helpers';
import { RunStore } from '../src/server/store';

const cleanups: (() => Promise<unknown>)[] = [];
afterEach(async () => { for (const cleanup of cleanups.splice(0)) await cleanup(); });
async function fresh() { const result = await workspace(); cleanups.push(result.cleanup); return result.store; }
function pathFor(store: RunStore, run: { createdAt:string; runId:string }) { return join(store.directory,'runs',run.createdAt.slice(0,4),run.createdAt.slice(5,7),`${run.runId}.json`); }

describe('immutable run contract', () => {
  test('R-1/R-2 corrections append exact inverses; original bytes never change', async () => {
    const store = await fresh();
    const result = await store.execute(() => journalCandidate());
    const before = await readFile(pathFor(store,result.run),'utf8');
    await store.execute((runs) => planReversal({ originalRunId:result.run.runId, occurredOn:'2026-11-16', reason:'Correct synthetic entry', idempotencyKey:'reverse-once' },runs));
    expect(await readFile(pathFor(store,result.run),'utf8') === before).toBe(true);
    expect((await store.read()).length).toBe(2);
    await expect(store.execute((runs) => planReversal({ originalRunId:result.run.runId, occurredOn:'2026-11-16', reason:'Second correction', idempotencyKey:'reverse-again' },runs))).rejects.toThrow(/already reversed/);
  });
  test('R-2 an invalid run writes nothing', async () => {
    const store = await fresh();
    const candidate = journalCandidate();
    const effect = candidate.effects[0];
    if (effect?.type !== 'journal.posted') throw new Error('fixture');
    effect.entry.lines[0]!.debit = '2.0000' as typeof effect.entry.lines[0]['debit'];
    await expect(store.execute(() => candidate)).rejects.toThrow();
    expect((await store.read()).length).toBe(0);
  });
  test('R-3 repeated idempotency key returns the same run and zero writes', async () => {
    const store = await fresh();
    const candidate = journalCandidate();
    const first = await store.execute(() => candidate), second = await store.execute(() => candidate);
    expect(second.duplicate).toBe(true); expect(second.run.runId).toBe(first.run.runId); expect((await store.read()).length).toBe(1);
  });
  test('preview validates but writes zero runs', async () => {
    const store = await fresh(); await store.execute(() => journalCandidate(),true); expect((await store.read()).length).toBe(0);
  });
  test('idempotency keys cannot disclose records from a different action', async () => {
    const store = await fresh(); await store.execute(() => journalCandidate({ idempotencyKey:'shared-key' }));
    await expect(store.execute(() => journalCandidate({ idempotencyKey:'shared-key', input:{ different:true } }))).rejects.toThrow(/different action/);
  });
  test('R-4 rejects individually unbalanced entries even when the batch balances', async () => {
    const store = await fresh(); const candidate = journalCandidate();
    const first = candidate.effects[0]; if (first?.type !== 'journal.posted') throw new Error('fixture');
    const second = structuredClone(first); second.entry.entryId = randomUUID();
    first.entry.lines[0]!.debit = '1235.5000' as typeof first.entry.lines[0]['debit'];
    second.entry.lines[1]!.credit = '1235.5000' as typeof second.entry.lines[1]['credit'];
    candidate.effects.push(second); await expect(store.execute(() => candidate)).rejects.toThrow();
  });
  test('R-4 balances by entry in TWD, not transaction currency', () => {
    const effect = journalCandidate().effects[0]; if (effect?.type !== 'journal.posted') throw new Error('fixture');
    effect.entry.lines[0]!.txnAmount = '40.0000' as typeof effect.entry.lines[0]['txnAmount']; effect.entry.lines[0]!.txnCurrency = 'USD'; effect.entry.lines[0]!.fxRateId = 'public-evidence';
    expect(journalSchema.safeParse(effect.entry).success).toBe(true);
    effect.entry.lines[0]!.fxRateId = null; expect(journalSchema.safeParse(effect.entry).success).toBe(false);
  });
  test('R-5 paid order is a deposit, never revenue; shipment needs a date', async () => {
    const store = await fresh(); const candidate = journalCandidate(); const effect = candidate.effects[0]; if (effect?.type !== 'journal.posted') throw new Error('fixture');
    effect.entry.sourceEvent='order.placed'; expect(candidateSchema.safeParse(candidate).success).toBe(false);
    effect.entry.lines[1]!.account={ code:'2211', name:'Customer deposits' }; expect(candidateSchema.safeParse(candidate).success).toBe(true);
    effect.entry.sourceEvent='order.shipped'; await expect(store.execute(() => candidate)).rejects.toThrow(/shipment date/);
  });
  test('R-6 rejects plug account names', () => {
    const candidate = journalCandidate(); const effect=candidate.effects[0]; if(effect?.type!=='journal.posted') throw new Error('fixture');
    effect.entry.lines[0]!.account.name='Rounding'; expect(candidateSchema.safeParse(candidate).success).toBe(false);
  });
  test('R-7 close needs five distinct passing evidenced checks, then blocks backdating', async () => {
    const store = await fresh();
    const candidate: Candidate = candidateSchema.parse({ kind:'period.close', occurredOn:'2026-10-31',dataset:'SAMPLE',input:{}, idempotencyKey:'close-October',effects:[{ type:'period.closed',period:'2026-10',founderAuthorization:'synthetic-approval',gates:['G-1','G-2','G-3','G-4','G-5'].map((gate)=>({gate,status:'PASS',evidenceRef:'synthetic-gate-result'})) }] });
    const close=candidate.effects[0]; if(close?.type!=='period.closed') throw new Error('fixture');
    close.gates[0]!.status='NOT_RUNNABLE'; await expect(store.execute(()=>candidate)).rejects.toThrow(/five/);
    close.gates[0]!.status='PASS'; await store.execute(()=>candidate);
    await expect(store.execute(()=>journalCandidate())).rejects.toThrow(/closed/);
  });
  test('R-8 tampered run opens read-only, names the run, and blocks writes', async () => {
    const store = await fresh(); const {run}=await store.execute(()=>journalCandidate()); const filename=pathFor(store,run);
    await chmod(filename,0o600); await writeFile(filename,canonical({...run,idempotencyKey:'tampered'}));
    const status=await store.status(); expect(status.readOnly).toBe(true); expect(status.badRunId).toBe(run.runId);
    await expect(store.execute(()=>journalCandidate())).rejects.toThrow(/Read-only/);
  });
  test('R-8 missing chain predecessor is detected', async () => {
    const store=await fresh(); const first=await store.execute(()=>journalCandidate()); await store.execute(()=>journalCandidate());
    await rm(pathFor(store,first.run)); expect((await store.status()).readOnly).toBe(true);
  });
  test('R-9 independent store instances serialize parallel writes and duplicates', async () => {
    const store=await fresh(); const peer=new RunStore(store.directory), candidate=journalCandidate();
    const results=await Promise.all(Array.from({length:12},(_,index)=>(index%2?peer:store).execute(()=>candidate)));
    expect(results.filter((result)=>!result.duplicate).length).toBe(1); expect((await store.read()).length).toBe(1);
  });
  test('R-10 rejects buyer details outside customer runs without echoing them', async () => {
    const store=await fresh(); const input={ buyerName:['Synthetic','Buyer'].join(' ') }; let rejected=false;
    try { await store.execute(()=>journalCandidate({input})); } catch(error) { rejected=error instanceof Error && !error.message.includes(input.buyerName); }
    expect(rejected).toBe(true); expect((await store.read()).length).toBe(0);
  });
  test('R-10 protected customer fields never appear in the projection cache', async () => {
    const store=await fresh(); const name=['Synthetic','Private','Buyer'].join(' ');
    await store.execute(()=>candidateSchema.parse({kind:'customer.create',dataset:'SAMPLE',occurredOn:'2026-10-02',input:{},idempotencyKey:'customer-safe-reference',effects:[{type:'customer.created',customer:{customerId:randomUUID(),name,email:null,address:null}}]}));
    await store.status(); const cache=await readFile(join(store.directory,'.cache','status.json'),'utf8'); expect(cache.includes(name)).toBe(false);
  });
  test('activation refuses absent seed reversal and real approved opening', async () => {
    const store=await fresh(); await expect(store.execute(()=>candidateSchema.parse({kind:'dataset.activate',dataset:'SAMPLE',occurredOn:'2026-11-16',input:{},idempotencyKey:'activate',effects:[{type:'dataset.activated'}]}))).rejects.toThrow(/sample seed/);
  });
  test('stock uses whole pieces and damaged pieces have zero sellable value', () => {
    const candidate={kind:'stock.count',dataset:'SAMPLE',occurredOn:'2026-10-02',input:{},idempotencyKey:'count',effects:[{type:'stock.moved',move:{moveId:randomUUID(),sku:'SYNTHETIC',qtyPieces:'1.5',condition:'sellable',valueTwd:'1.0000'}}]};
    expect(candidateSchema.safeParse(candidate).success).toBe(false);
    candidate.effects[0]!.move.qtyPieces='1'; candidate.effects[0]!.move.condition='damaged'; expect(candidateSchema.safeParse(candidate).success).toBe(false);
  });
  test('attachments are content addressed, immutable, and duplicate-safe', async () => {
    const store=await fresh(); const first=await store.putAttachment(Buffer.from('synthetic,evidence\n'),'csv');
    expect(await store.putAttachment(Buffer.from('synthetic,evidence\n'),'csv')).toBe(first); expect((await readdir(join(store.directory,'attachments'))).length).toBe(1);
  });
});
