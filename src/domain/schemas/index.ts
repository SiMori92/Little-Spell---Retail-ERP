import { z } from 'zod';
import Decimal from '../decimal';
import { approvedChartRows } from '../chart';
import { decimalSchema, dateSchema, datasetSchema, hashSchema, idSchema } from './primitives';
import { masterEffectSchemas } from './masters';
import { sellingEffectSchemas } from './selling';
import { procurementEffectSchemas } from './procurement';
import { accountingEffectSchemas } from './accounting';
import { closeEffectSchemas } from './closing';
export { decimalSchema, dateSchema, datasetSchema, hashSchema, idSchema } from './primitives';
export type { Money } from './primitives';

export const metaSchema = z.strictObject({ schemaVersion: z.literal(1), dataset: datasetSchema, createdAt: z.iso.datetime() });
export const accountSchema = z.strictObject({ code: z.string().regex(/^\d{4}$/).refine((code) => approvedChartRows.some((account) => account.account_code === code), 'Choose an account from the approved chart.'), name: z.string().min(1).max(120).refine((name) => !/suspense|rounding|difference/i.test(name), 'Plug accounts are not allowed.') });
export const journalLineSchema = z.strictObject({
  account: accountSchema,
  debit: decimalSchema,
  credit: decimalSchema,
  txnAmount: decimalSchema.nullable(),
  txnCurrency: z.string().regex(/^[A-Z]{3}$/).nullable(),
  fxRateId: z.string().min(1).nullable()
  ,sku:z.string().min(1).optional(),qtyPieces:z.string().regex(/^-?(?:0|[1-9]\d*)$/).optional(),memo:z.string().max(500).optional(),sourceRef:z.string().max(255).optional()
}).superRefine((line, context) => {
  const debit = new Decimal(line.debit), credit = new Decimal(line.credit);
  if (debit.isNegative() || credit.isNegative() || (debit.gt(0) && credit.gt(0))) context.addIssue({ code: 'custom', message: 'Each line must have one non-negative payment side.' });
  const triple = [line.txnAmount, line.txnCurrency, line.fxRateId];
  if (triple.some((value) => value !== null) && !triple.every((value) => value !== null)) context.addIssue({ code: 'custom', message: 'Include the transaction amount, currency, and exchange-rate evidence together.' });
});
export const journalSchema = z.strictObject({
  entryId: idSchema, occurredOn: dateSchema, sourceEvent: z.string().min(1), lines: z.array(journalLineSchema).min(2)
}).superRefine((entry, context) => {
  const balance = entry.lines.reduce((total, line) => total.plus(line.debit).minus(line.credit), new Decimal(0));
  if (!balance.isZero()) context.addIssue({ code: 'custom', message: 'This entry does not balance in Taiwan dollars.' });
  if (entry.sourceEvent === 'order.placed' && (entry.lines.some((line) => line.account.code.startsWith('4')) || !entry.lines.some((line) => line.account.code === '2211' && new Decimal(line.credit).gt(0)))) context.addIssue({ code: 'custom', message: 'A paid order is held as a customer deposit until dispatch.' });
});
export const stockMoveSchema = z.strictObject({
  moveId: idSchema, sku: z.string().min(1), qtyPieces: z.string().regex(/^-?(?:0|[1-9]\d*)$/, 'Quantity must be a whole number of pieces.'), condition: z.enum(['sellable', 'damaged']), valueTwd: decimalSchema
}).refine((move) => move.condition !== 'damaged' || new Decimal(move.valueTwd).isZero(), 'Damaged pieces have no sellable stock value.');
export const customerSchema = z.strictObject({ customerId: idSchema, name: z.string().min(1).max(200), email: z.email().nullable(), address: z.string().max(1000).nullable() });
export const gateResultSchema = z.strictObject({ gate: z.enum(['G-1', 'G-2', 'G-3', 'G-4', 'G-5']), status: z.enum(['PASS', 'FAIL', 'NOT_RUNNABLE']), evidenceRef: z.string().min(1) });
export const effectSchema = z.discriminatedUnion('type', [
  ...masterEffectSchemas,
  ...sellingEffectSchemas,
  ...procurementEffectSchemas,
  ...accountingEffectSchemas,
  ...closeEffectSchemas,
  z.strictObject({ type: z.literal('journal.posted'), entry: journalSchema, opening: z.enum(['SAMPLE_SEED', 'REAL_OPENING']).nullable(), founderAuthorization: z.string().min(1).nullable() }),
  z.strictObject({ type: z.literal('stock.moved'), move: stockMoveSchema }),
  z.strictObject({ type: z.literal('period.closed'), period: z.string().regex(/^\d{4}-(?:0[1-9]|1[0-2])$/), founderAuthorization: z.string().min(1), gates: z.array(gateResultSchema).length(5) }),
  z.strictObject({ type: z.literal('run.reversed'), originalRunId: idSchema }),
  z.strictObject({ type: z.literal('dataset.activated') }),
  z.strictObject({ type: z.literal('customer.created'), customer: customerSchema }),
  z.strictObject({ type: z.literal('seed.registered'), manifestHash: hashSchema, fixtureCount: z.int().positive() })
]);
export const runSchema = z.strictObject({
  runId: idSchema, kind: z.enum(['sample.seed', 'journal.post', 'stock.count', 'period.close', 'reversal', 'dataset.activate', 'customer.create', 'masters.record', 'masters.import', 'masters.bootstrap', 'selling.record', 'procurement.record','accounting.record','close.record','dataset.opening']),
  createdAt: z.iso.datetime(), occurredOn: dateSchema, dataset: datasetSchema, schemaVersion: z.literal(1),
  input: z.json(), effects: z.array(effectSchema).min(1), idempotencyKey: z.string().min(1).max(255), prevHash: hashSchema, hash: hashSchema
});
export const reversalPayloadSchema = z.strictObject({ originalRunId: idSchema, occurredOn: dateSchema, reason: z.string().min(1).max(500), idempotencyKey: z.string().min(1).max(255) });
export type Run = z.infer<typeof runSchema>;
export type Effect = z.infer<typeof effectSchema>;
export type Dataset = z.infer<typeof datasetSchema>;
export type Journal = z.infer<typeof journalSchema>;
export const candidateSchema = runSchema.omit({ runId: true, createdAt: true, schemaVersion: true, prevHash: true, hash: true });
export type Candidate = z.infer<typeof candidateSchema>;
export const statusPayloadSchema = z.strictObject({});
export const activityRowSchema = z.strictObject({ runId: idSchema, kind: runSchema.shape.kind, occurredOn: dateSchema, dataset: datasetSchema, reversible: z.boolean() });
export type ActivityRow = z.infer<typeof activityRowSchema>;
export const procurementResultSchema=z.strictObject({ok:z.literal(true),runId:idSchema.nullable(),effects:z.array(effectSchema),summary:z.array(z.string()),warnings:z.array(z.string()),duplicate:z.boolean(),preview:z.boolean(),headHash:hashSchema});
