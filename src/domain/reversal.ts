import { randomUUID } from 'node:crypto';
import { DomainError } from './errors';
import { inverseEffects } from './invariants';
import { reversalPayloadSchema, type Candidate, type Run } from './schemas';

export function planReversal(raw: unknown, runs: readonly Run[]): Candidate {
  const input = reversalPayloadSchema.parse(raw);
  const original = runs.find((run) => run.runId === input.originalRunId);
  if (!original) throw new DomainError('originalRunId', 'Choose an existing record to reverse.');
  return {
    kind: 'reversal', occurredOn: input.occurredOn, dataset: original.dataset,
    input, idempotencyKey: input.idempotencyKey,
    effects: [{ type: 'run.reversed', originalRunId: original.runId }, ...inverseEffects(original, randomUUID, input.occurredOn)]
  };
}
