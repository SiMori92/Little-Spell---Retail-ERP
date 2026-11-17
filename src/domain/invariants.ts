import Decimal from './decimal';
import { DomainError } from './errors';
import { digest } from './canonical';
import { type Candidate, type Dataset, type Effect, type Run } from './schemas';
import { validateMasterCandidate } from './masters';
import { containsContactDetails } from './privacy';
import { validateSellingCandidate } from './selling';
import { validateProcurementCandidate } from './procurement';
import { validateAccounting } from './accounting';
import { validateClose } from './closing';
import { validateActivation } from './activation';
import { approvedChartRows } from './chart';

function fail(message: string): never { throw new DomainError('record', message); }
const reversed = (runs: readonly Run[]) => new Set(runs.flatMap((run) => run.effects.flatMap((effect) => effect.type === 'run.reversed' ? [effect.originalRunId] : [])));
export const currentDataset = (runs: readonly Run[]): Dataset => runs.some((run) => run.effects.some((effect) => effect.type === 'dataset.activated')) ? 'ACTUAL' : 'SAMPLE';

export function inverseEffects(original: Run, entryId: () => string, occurredOn: string): Effect[] {
  if (original.effects.some((effect) => !['journal.posted', 'stock.moved', 'seed.registered'].includes(effect.type))) fail('This record cannot be reversed by the foundation workflow.');
  return original.effects.flatMap((effect): Effect[] => {
    if (effect.type === 'journal.posted') return [{ ...effect, opening: null, founderAuthorization: null, entry: { ...effect.entry, entryId: entryId(), occurredOn, sourceEvent: 'entry.reversed', lines: effect.entry.lines.map((line) => ({ ...line, debit: line.credit, credit: line.debit, txnAmount: line.txnAmount === null ? null : new Decimal(line.txnAmount).negated().toFixed(4) as typeof line.txnAmount })) } }];
    if (effect.type === 'stock.moved') return [{ type: 'stock.moved', move: { ...effect.move, moveId: entryId(), qtyPieces: new Decimal(effect.move.qtyPieces).negated().toFixed(0), valueTwd: new Decimal(effect.move.valueTwd).negated().toFixed(4) as typeof effect.move.valueTwd } }];
    return [];
  });
}

function privateContent(value: unknown, allowMasterNames = false): boolean {
  if (typeof value === 'string') return containsContactDetails(value);
  if (Array.isArray(value)) return value.some((item) => privateContent(item,allowMasterNames));
  if (value && typeof value === 'object') return Object.entries(value).some(([key, item]) => {
    if (allowMasterNames && ['csvText','suppliersCsv','productsCsv'].includes(key)) return false;
    return /^(?:buyer|buyerName|buyerEmail|customerName|email|address|shipName|shipAddress)$/i.test(key) || !allowMasterNames && /^name$/i.test(key) || privateContent(item,allowMasterNames);
  });
  return false;
}

export function validateCandidate(candidate: Candidate, runs: readonly Run[]): void {
  if(candidate.kind==='accounting.record')validateAccounting(candidate,runs);
  if(candidate.kind==='close.record')validateClose(candidate,runs);
  if(candidate.kind==='dataset.opening')validateActivation(candidate,runs);
  if (candidate.kind === 'procurement.record') validateProcurementCandidate(candidate,runs);
  if (candidate.kind === 'selling.record') validateSellingCandidate(candidate,runs);
  const masterAction = candidate.kind.startsWith('masters.');
  if (masterAction) validateMasterCandidate(candidate,runs);
  const dataset = currentDataset(runs);
  if (candidate.dataset !== dataset && !(['journal.post','dataset.opening'].includes(candidate.kind) && candidate.dataset === 'ACTUAL' && dataset === 'SAMPLE' && candidate.effects.every((effect) => effect.type === 'journal.posted' && effect.opening === 'REAL_OPENING' && Boolean(effect.founderAuthorization)))) fail('This record belongs to a different dataset.');
  const closed = new Set(runs.flatMap((run) => run.effects.flatMap((effect) => effect.type === 'period.closed' && run.dataset === candidate.dataset ? [effect.period] : [])));
  if (closed.has(candidate.occurredOn.slice(0, 7))) fail('This month is closed. Create a correction in an open month.');
  if (candidate.kind !== 'customer.create' && privateContent({ input: candidate.input, idempotencyKey: candidate.idempotencyKey, effects: candidate.effects.map((effect) => effect.type === 'journal.posted' ? { ...effect, entry: { ...effect.entry, lines: effect.entry.lines.map((line) => ({ ...line, account: { code: line.account.code } })) } } : effect) },masterAction)) fail('Keep buyer details in the protected customer workflow.');
  const expected: Record<Candidate['kind'], readonly Effect['type'][]> = {
    'accounting.record':['accounting.fx','accounting.fact','accounting.posted','accounting.reversed','accounting.cause','accounting.inventory-tags','accounting.receipt-import','accounting.stock-policy','journal.posted'],
    'close.record':['close.reviewed','close.attempted','period.closed'],
    'dataset.opening':['journal.posted'],
    'procurement.record':['procurement.account','procurement.po','procurement.status','procurement.receipt','procurement.invoice','procurement.payment','procurement.count','procurement.matched','procurement.movement','procurement.import','journal.posted'],
    'selling.record':['selling.order','selling.statement','selling.deal','selling.shipment','selling.event','selling.verified','selling.import'],
    'sample.seed': ['seed.registered', 'journal.posted'], 'journal.post': ['journal.posted'], 'stock.count': ['stock.moved', 'journal.posted'],
    'period.close': ['period.closed'], reversal: ['run.reversed', 'journal.posted', 'stock.moved'], 'dataset.activate': ['dataset.activated'], 'customer.create': ['customer.created']
    , 'masters.record':['supplier.recorded','product.recorded','channel.recorded','account.recorded','business.recorded','opening.prepared'], 'masters.import':['supplier.recorded','product.recorded','channel.recorded','account.recorded','masters.imported'], 'masters.bootstrap':['supplier.recorded','product.recorded','channel.recorded','account.recorded','masters.imported','masters.initialized']
  };
  if (candidate.effects.some((effect) => !expected[candidate.kind].includes(effect.type))) fail('This action contains an unrelated change.');
  if (candidate.kind === 'sample.seed' && (runs.length > 0 || candidate.dataset !== 'SAMPLE' || !candidate.effects.some((effect) => effect.type === 'seed.registered'))) fail('The sample seed can only be registered once, in an empty workspace.');
  const seenEntries = new Set(runs.flatMap((run) => run.effects.flatMap((effect) => effect.type === 'journal.posted' ? [effect.entry.entryId] : [])));
  const seenMoves = new Set(runs.flatMap((run) => run.effects.flatMap((effect) => effect.type === 'stock.moved' ? [effect.move.moveId] : [])));
  for (const effect of candidate.effects) {
    if((effect.type==='accounting.fact'&&closed.has(effect.record.date.slice(0,7)))||(effect.type==='accounting.fx'&&closed.has(effect.record.date.slice(0,7))))fail('The source date belongs to a closed month.');
    if (effect.type === 'journal.posted') {
      if(effect.entry.lines.some(line=>approvedChartRows.find(a=>a.account_code===line.account.code)?.is_reserved==='true'))fail('A reserved account cannot receive a posting.');
      if (candidate.kind !== 'procurement.record' && effect.entry.occurredOn !== candidate.occurredOn || closed.has(effect.entry.occurredOn.slice(0, 7))) fail('The entry date must match the action date and an open month.');
      if (seenEntries.has(effect.entry.entryId)) fail('This journal entry already exists.');
      seenEntries.add(effect.entry.entryId);
      if (effect.opening === 'REAL_OPENING' && (candidate.dataset !== 'ACTUAL' || !effect.founderAuthorization)) fail('Real opening balances need recorded founder approval.');
      if (effect.opening === 'SAMPLE_SEED' && candidate.kind !== 'sample.seed') fail('Only the first sample run may create a seed entry.');
      if (candidate.kind!=='accounting.record' && effect.entry.sourceEvent === 'order.shipped' && (typeof candidate.input !== 'object' || candidate.input === null || !('shipDate' in candidate.input) || candidate.input.shipDate !== candidate.occurredOn)) fail('Dispatch needs a matching shipment date before revenue can be recognised.');
    }
    if (effect.type === 'stock.moved') {
      if (seenMoves.has(effect.move.moveId)) fail('This stock movement already exists.');
      seenMoves.add(effect.move.moveId);
    }
    if (effect.type === 'period.closed') {
      if (candidate.kind!=='close.record' && effect.period !== candidate.occurredOn.slice(0, 7) || effect.gates.some((gate) => gate.status !== 'PASS') || new Set(effect.gates.map((gate) => gate.gate)).size !== 5) fail('All five distinct checks must pass with evidence before closing.');
    }
  }
  if (candidate.kind === 'reversal') {
    const references = candidate.effects.filter((effect) => effect.type === 'run.reversed');
    if (references.length !== 1) fail('Choose exactly one original record to reverse.');
    const original = runs.find((run) => run.runId === references[0]?.originalRunId);
    if (!original || original.dataset !== candidate.dataset || reversed(runs).has(original.runId)) fail('The original is missing, belongs to another dataset, or was already reversed.');
    const actual = candidate.effects.filter((effect) => effect.type !== 'run.reversed');
    const expectedInverse = inverseEffects(original, () => 'ignored', candidate.occurredOn);
    const normalized = (effects: Effect[]) => effects.map((effect) => effect.type === 'journal.posted' ? { ...effect, entry: { ...effect.entry, entryId: 'ignored' } } : effect.type === 'stock.moved' ? { ...effect, move: { ...effect.move, moveId: 'ignored' } } : effect);
    if (digest(normalized(actual)) !== digest(normalized(expectedInverse))) fail('A reversal must exactly undo the original effects.');
  }
  if (candidate.kind === 'dataset.activate') {
    if (dataset === 'ACTUAL' || candidate.effects.length !== 1) fail('Actual data is already active, or this action contains unrelated changes.');
    const reversals = reversed(runs);
    const seeds = runs.filter((run) => run.effects.some((effect) => effect.type === 'journal.posted' && effect.opening === 'SAMPLE_SEED' || effect.type==='seed.registered'));
    const openings = runs.filter((run) => run.dataset === 'ACTUAL' && !reversals.has(run.runId) && run.effects.some((effect) => effect.type === 'journal.posted' && effect.opening === 'REAL_OPENING' && Boolean(effect.founderAuthorization)));
    if (!seeds.length || seeds.some((run) => !reversals.has(run.runId)) || !openings.length) fail('Reverse the sample seed and post founder-approved real opening balances before switching.');
  }
}
