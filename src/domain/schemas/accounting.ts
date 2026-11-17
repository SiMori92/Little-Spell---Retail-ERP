import { z } from 'zod';
import Decimal from '../decimal';
import { dateSchema, decimalSchema, hashSchema, idSchema } from './primitives';
export const evidenceText=z.string().trim().min(1,'Enter the evidence reference.').max(255);
export const positiveAmount=decimalSchema.refine(v=>new Decimal(v).gt(0),'Enter an amount greater than zero.');
export const periodSchema=z.string().regex(/^\d{4}-(?:0[1-9]|1[0-2])$/,'Choose a month.');
export const stockPolicySchema=z.strictObject({sku:evidenceText,reorderPoint:z.string().regex(/^(?:0|[1-9]\d*)$/,'Use a whole number of pieces.'),evidenceRef:evidenceText});
export const fxSchema=z.strictObject({id:hashSchema,date:dateSchema,currency:z.string().regex(/^[A-Z]{3}$/),rate:z.string().regex(/^(?:0|[1-9]\d{0,7})(?:\.\d{1,6})?$/,{error:'Use a positive rate with up to six decimal places.',abort:true}).refine(v=>new Decimal(v).gt(0),'Enter a positive rate.'),evidenceRef:evidenceText,source:z.literal('Bank of Taiwan')});
export const expenseSchema=z.strictObject({date:dateSchema,category:z.enum(['advertising','rent','software','professional','utilities','wages','bank_fee','other']),amountTwd:positiveAmount,settledVia:z.enum(['bank','payable']),bankAccount:z.enum(['1121','1111']),channel:z.enum(['','etsy','meta','other']),description:evidenceText,evidenceRef:evidenceText}).refine(r=>r.category==='advertising'?r.channel!=='':r.channel==='','Advertising needs a channel; other expenses do not.');
export const manualSchema=z.discriminatedUnion('eventType',[
 z.strictObject({eventType:z.literal('period.accrued'),amount:positiveAmount,expenseAccount:z.string().regex(/^\d{4}$/),accrualAccount:z.enum(['2191','2193','2197']),basisNote:evidenceText}),
 z.strictObject({eventType:z.literal('period.accrual_reversed'),originalId:hashSchema}),
 z.strictObject({eventType:z.literal('period.revalued'),amount:positiveAmount,account:z.string().regex(/^\d{4}$/),direction:z.enum(['gain','loss']),rateSource:evidenceText}),
 z.strictObject({eventType:z.literal('owner.funds_moved'),amount:positiveAmount,fundsType:z.enum(['capital','drawings','loan'])}),
 z.strictObject({eventType:z.literal('tax.assessed'),amount:positiveAmount,needsProfessionalConfirmation:z.literal(true)}),
 z.strictObject({eventType:z.literal('tax.paid'),amount:positiveAmount})
]);
export const accountingFactSchema=z.strictObject({id:hashSchema,date:dateSchema,evidenceRef:evidenceText,detail:z.discriminatedUnion('kind',[
 z.strictObject({kind:z.literal('manual'),record:manualSchema}),
 z.strictObject({kind:z.literal('expense'),record:expenseSchema}),
 z.strictObject({kind:z.literal('freight-accrual'),orderId:evidenceText,amount:positiveAmount,basisNote:evidenceText}),
 z.strictObject({kind:z.literal('freight-invoice'),originalId:hashSchema,amount:positiveAmount}),
 z.strictObject({kind:z.literal('duty'),orderId:evidenceText,position:z.enum(['DDP','DDU','unknown']),amount:decimalSchema}),
 z.strictObject({kind:z.literal('duty-invoice'),originalId:hashSchema,amount:positiveAmount})
])});
const request={occurredOn:dateSchema,idempotencyKey:evidenceText,expectedHeadHash:hashSchema.nullable().default(null)};
export const accountingPayloadSchema=z.discriminatedUnion('action',[
 z.strictObject({action:z.literal('fx'),...request,date:dateSchema,currency:z.string().regex(/^[A-Z]{3}$/),rate:fxSchema.shape.rate,evidenceRef:evidenceText}),
 z.strictObject({action:z.literal('manual'),...request,record:manualSchema,evidenceRef:evidenceText}),
 z.strictObject({action:z.literal('expense'),...request,record:expenseSchema}),
 z.strictObject({action:z.literal('fact'),...request,detail:accountingFactSchema.shape.detail,evidenceRef:evidenceText}),
 z.strictObject({action:z.literal('post'),...request,eventId:hashSchema}),
 z.strictObject({action:z.literal('inventory-evidence'),...request,evidenceRef:evidenceText}),
 z.strictObject({action:z.literal('import-receipts'),...request,filename:evidenceText,csvText:z.string().min(1,'Choose a CSV file.').max(524288)}),
 z.strictObject({action:z.literal('reorder'),...request,record:stockPolicySchema}),
 z.strictObject({action:z.literal('reverse'),...request,entryId:idSchema,reason:evidenceText}),
 z.strictObject({action:z.literal('cause'),...request,lineId:evidenceText,cause:evidenceText,evidenceRef:evidenceText,actor:evidenceText})
]);
export const accountingEffectSchemas=[
 z.strictObject({type:z.literal('accounting.stock-policy'),record:stockPolicySchema}),
 z.strictObject({type:z.literal('accounting.receipt-import'),sourceHash:hashSchema,records:z.int().positive()}),
 z.strictObject({type:z.literal('accounting.fx'),record:fxSchema}),
 z.strictObject({type:z.literal('accounting.fact'),record:accountingFactSchema}),
 z.strictObject({type:z.literal('accounting.posted'),eventId:hashSchema,entryId:idSchema.nullable(),memo:evidenceText}),
 z.strictObject({type:z.literal('accounting.reversed'),entryId:idSchema,reversalId:idSchema,reason:evidenceText}),
 z.strictObject({type:z.literal('accounting.cause'),lineId:evidenceText,cause:evidenceText,evidenceRef:evidenceText,actor:evidenceText})
 ,z.strictObject({type:z.literal('accounting.inventory-tags'),evidenceRef:evidenceText,tags:z.array(z.strictObject({entryId:idSchema,lineIndex:z.int().nonnegative(),sku:evidenceText,qtyPieces:z.string().regex(/^-?(?:0|[1-9]\d*)$/).nullable()})).min(1)})
] as const;
export type AccountingPayload=z.infer<typeof accountingPayloadSchema>;
export type AccountingFact=z.infer<typeof accountingFactSchema>;
export type Fx=z.infer<typeof fxSchema>;
