import { z } from 'zod';
import Decimal from '../decimal';
import { dateSchema, decimalSchema, idSchema, hashSchema, datasetSchema } from './primitives';
import { chartAccountSchema } from './masters';

const text=z.string().trim().min(1,'Enter a value.').max(255);
export const documentNumberSchema=z.string().regex(/^[A-Z0-9][A-Z0-9-]{0,31}$/,'Use an uppercase document reference with letters, digits, and hyphens.');
export const poNumberSchema=z.string().regex(/^PO-\d{4}-\d{3}$/,'Use a reference such as PO-2026-001.');
export const wholePiecesSchema=z.string().regex(/^(?:0|[1-9]\d{0,9})$/,{error:'Quantity must be a whole number of pieces; enter zero when counted as zero.',abort:true});
const positivePieces=wholePiecesSchema.refine(value=>new Decimal(value).gt(0),'Quantity must be a positive whole number of pieces.');
export const nonnegativeMoneySchema=decimalSchema.refine(value=>!new Decimal(value).isNegative(),'Use a non-negative amount.').transform(value=>decimalSchema.parse(new Decimal(value).toFixed(4)));
const positiveMoney=nonnegativeMoneySchema.refine(value=>new Decimal(value).gt(0),'Use an amount greater than zero.');
export const poFileStatusSchema=z.enum(['draft','sent','acknowledged','cancelled']);
export const poStatusSchema=z.enum(['draft','sent','acknowledged','cancelled','received','short_closed','closed']);
export const poLineSchema=z.strictObject({lineNo:z.int().min(1).max(500),sku:text,qtyPieces:positivePieces,unitPriceTwd:positiveMoney,setupChargeTwd:nonnegativeMoneySchema,lineTotalTwd:nonnegativeMoneySchema.optional(),moqPieces:positivePieces.nullable(),artworkRef:z.string().max(255),evidenceRef:text}).transform(line=>({...line,lineTotalTwd:line.lineTotalTwd??decimalSchema.parse(new Decimal(line.qtyPieces).times(line.unitPriceTwd).plus(line.setupChargeTwd).toFixed(4))})).superRefine((line,context)=>{
  if(!new Decimal(line.qtyPieces).times(line.unitPriceTwd).plus(line.setupChargeTwd).eq(line.lineTotalTwd))context.addIssue({code:'custom',path:['lineTotalTwd'],message:'Line total must equal pieces times per-piece price plus setup.'});
  if(line.moqPieces&&new Decimal(line.qtyPieces).lt(line.moqPieces))context.addIssue({code:'custom',path:['qtyPieces'],message:'The order quantity is below the evidenced minimum order quantity.'});
});
export const purchaseOrderSchema=z.strictObject({poNumber:poNumberSchema,supplierRef:z.string().regex(/^SUP-\d{3}$/),poDate:dateSchema,targetDeliveryDate:dateSchema,currency:z.literal('TWD'),paymentTerms:text,incoterm:z.enum(['EXW','FCA','CPT','CIP','DAP','DPU','DDP','FAS','FOB','CFR','CIF']),quoteRef:text,status:poFileStatusSchema,lines:z.array(poLineSchema).min(1).max(500)}).superRefine((record,context)=>{
  if(record.targetDeliveryDate<record.poDate)context.addIssue({code:'custom',path:['targetDeliveryDate'],message:'The delivery target cannot be before the order date.'});
  if(record.lines.some((line,index)=>line.lineNo!==index+1))context.addIssue({code:'custom',path:['lines'],message:'Line numbers must start at one, without gaps or duplicates.'});
});
export const receiptLineSchema=z.strictObject({lineNo:z.int().min(1).max(500),sku:text,qtyGood:wholePiecesSchema,qtyDamaged:wholePiecesSchema,damagedCredited:z.boolean(),shortClose:z.boolean(),shortCloseReason:z.string().max(255),evidenceRef:text}).superRefine((line,context)=>{
  if(line.damagedCredited&&new Decimal(line.qtyDamaged).isZero())context.addIssue({code:'custom',path:['damagedCredited'],message:'Only damaged pieces can be credited.'});
  if(line.shortClose!==Boolean(line.shortCloseReason))context.addIssue({code:'custom',path:['shortCloseReason'],message:'A short-close needs a reason; a full delivery must not have one.'});
  if(new Decimal(line.qtyGood).plus(line.damagedCredited?'0':line.qtyDamaged).lte(0))context.addIssue({code:'custom',path:['qtyGood'],message:'A receipt line must accept good or uncredited damaged pieces.'});
});
export const receiptSchema=z.strictObject({poNumber:poNumberSchema,receiptNo:documentNumberSchema,receivedOn:dateSchema,lines:z.array(receiptLineSchema).min(1).max(500)}).refine(record=>new Set(record.lines.map(line=>line.lineNo)).size===record.lines.length,'Receipt line numbers repeat.');
export const invoiceLineSchema=z.strictObject({lineNo:z.int().min(1).max(500),sku:text,qtyInvoiced:positivePieces,unitPriceTwd:positiveMoney,setupChargeTwd:nonnegativeMoneySchema,lineAmountTwd:nonnegativeMoneySchema.optional(),statedTaxTwd:nonnegativeMoneySchema.nullable().default(null)}).transform(line=>({...line,lineAmountTwd:line.lineAmountTwd??decimalSchema.parse(new Decimal(line.qtyInvoiced).times(line.unitPriceTwd).plus(line.setupChargeTwd).toFixed(4))})).refine(line=>new Decimal(line.qtyInvoiced).times(line.unitPriceTwd).plus(line.setupChargeTwd).eq(line.lineAmountTwd),'The invoice line amount must equal pieces times price plus setup.');
export const invoiceSchema=z.strictObject({invoiceNo:documentNumberSchema,guiNo:z.string().regex(/^(?:[A-Z]{2}\d{8})?$/,'Use two letters and eight digits, or leave the GUI number blank.'),invoiceDate:dateSchema,poNumber:poNumberSchema,receiptNo:documentNumberSchema,freightTwd:nonnegativeMoneySchema,taxTwd:nonnegativeMoneySchema,taxCreditableTwd:nonnegativeMoneySchema,invoiceTotalTwd:nonnegativeMoneySchema,depositAppliedTwd:nonnegativeMoneySchema,evidenceRef:text,lines:z.array(invoiceLineSchema).min(1).max(500)}).superRefine((record,context)=>{
  if(new Decimal(record.taxCreditableTwd).gt(record.taxTwd)||new Decimal(record.taxCreditableTwd).gt(0)&&!record.guiNo)context.addIssue({code:'custom',path:['taxCreditableTwd'],message:'Creditable tax cannot exceed tax and needs a valid GUI number.'});
  const total=record.lines.reduce((sum,line)=>sum.plus(line.lineAmountTwd),new Decimal(record.freightTwd).plus(record.taxTwd));
  if(!total.eq(record.invoiceTotalTwd))context.addIssue({code:'custom',path:['invoiceTotalTwd'],message:'The invoice total must equal lines plus supplier freight and tax.'});
  const stated=record.lines.filter(line=>line.statedTaxTwd!==null);
  if(stated.length&&(stated.length!==record.lines.length||!stated.reduce((sum,line)=>sum.plus(line.statedTaxTwd!),new Decimal(0)).eq(record.taxTwd)))context.addIssue({code:'custom',path:['lines'],message:'State tax on every line or on none; stated line taxes must sum to the invoice tax.'});
  if(new Set(record.lines.map(line=>line.lineNo)).size!==record.lines.length)context.addIssue({code:'custom',path:['lines'],message:'Invoice line numbers repeat.'});
});
export const paymentKindSchema=z.enum(['deposit','balance','deposit_refund','deposit_forfeit']);
export const supplierPaymentSchema=z.strictObject({paymentRef:documentNumberSchema,paidOn:dateSchema,supplierRef:z.string().regex(/^SUP-\d{3}$/),poNumber:poNumberSchema,invoiceNo:z.string().max(32),paymentKind:paymentKindSchema,amountTwd:positiveMoney,bankAccount:z.literal('1121'),bankRef:z.string().max(255),evidenceRef:text}).superRefine((record,context)=>{
  if((record.paymentKind==='balance')!==Boolean(record.invoiceNo))context.addIssue({code:'custom',path:['invoiceNo'],message:'Only a balance payment must name a supplier invoice.'});
  if((record.paymentKind!=='deposit_forfeit')!==Boolean(record.bankRef))context.addIssue({code:'custom',path:['bankRef'],message:'Record a bank reference for cash movements; forfeiture has no bank movement.'});
});
export const countLineSchema=z.strictObject({sku:text,qtyPieces:wholePiecesSchema,agreedUnitCostTwd:nonnegativeMoneySchema,condition:z.enum(['sellable','damaged_unsellable'])}).superRefine((line,context)=>{
  if(line.condition==='damaged_unsellable'&&(new Decimal(line.qtyPieces).lte(0)||!new Decimal(line.agreedUnitCostTwd).isZero()))context.addIssue({code:'custom',path:['agreedUnitCostTwd'],message:'Damaged pieces need a positive count and zero sellable value.'});
});
export const stockCountSchema=z.strictObject({countedAt:dateSchema,evidenceRef:text,lines:z.array(countLineSchema).min(1).max(1000)}).refine(record=>new Set(record.lines.map(line=>`${line.sku}:${line.condition}`)).size===record.lines.length,'Each SKU and condition may appear only once.');
const request={occurredOn:dateSchema,idempotencyKey:text,expectedHeadHash:hashSchema.nullable().default(null)};
export const procurementAreaSchema=z.enum(['po','grn','inv','pay','counts']);
export const procurementPayloadSchema=z.discriminatedUnion('action',[
  z.strictObject({action:z.literal('po'),...request,previousRunId:idSchema.nullable(),record:purchaseOrderSchema}),
  z.strictObject({action:z.literal('receipt'),...request,record:receiptSchema}),
  z.strictObject({action:z.literal('invoice'),...request,record:invoiceSchema}),
  z.strictObject({action:z.literal('payment'),...request,record:supplierPaymentSchema}),
  z.strictObject({action:z.literal('count'),...request,record:stockCountSchema,founderConfirmed:z.boolean().refine(value=>value,'Confirm this is your own evidenced physical count.')}),
  z.strictObject({action:z.literal('import'),...request,area:procurementAreaSchema,filename:z.string().max(100),csvText:z.string().min(1,'Choose a CSV file.').max(524288),founderConfirmed:z.boolean().default(false)})
]);
export const landedInputSchema=z.strictObject({lineNo:z.int().positive(),sku:text,inventoryAccount:z.enum(['1231','1233']),qtyGood:wholePiecesSchema,qtyDamaged:wholePiecesSchema,lineAmount:nonnegativeMoneySchema,setup:nonnegativeMoneySchema,statedTax:nonnegativeMoneySchema.nullable()});
export const landedLineSchema=landedInputSchema.extend({freightShare:decimalSchema,taxShare:decimalSchema,landed:nonnegativeMoneySchema,damagedValue:nonnegativeMoneySchema,goodValue:nonnegativeMoneySchema});
export const receiptMatchSchema=z.strictObject({poNumber:poNumberSchema,receiptNo:documentNumberSchema,invoiceNo:documentNumberSchema,receivedOn:dateSchema,depositAppliedTwd:nonnegativeMoneySchema,invoiceStatedDepositTwd:nonnegativeMoneySchema,invoiceTotalTwd:nonnegativeMoneySchema,taxCreditableTwd:nonnegativeMoneySchema,lines:z.array(landedLineSchema),journalId:idSchema});
export const procurementMovementSchema=z.strictObject({moveId:idSchema,occurredOn:dateSchema,sku:text,kind:z.enum(['opening','received','adjusted']),qtyPieces:z.string().regex(/^-?(?:0|[1-9]\d*)$/),valueTwd:decimalSchema,sourceRef:text});
export const procurementEffectSchemas=[
  z.strictObject({type:z.literal('procurement.account'),record:chartAccountSchema,sourceRef:z.literal('app/acct/migrations/0008_supplier_prepayments_account.py')}),
  z.strictObject({type:z.literal('procurement.po'),record:purchaseOrderSchema,previousRunId:idSchema.nullable()}),
  z.strictObject({type:z.literal('procurement.status'),poNumber:poNumberSchema,status:poStatusSchema,effectiveOn:dateSchema}),
  z.strictObject({type:z.literal('procurement.receipt'),record:receiptSchema}),
  z.strictObject({type:z.literal('procurement.invoice'),record:invoiceSchema}),
  z.strictObject({type:z.literal('procurement.payment'),record:supplierPaymentSchema}),
  z.strictObject({type:z.literal('procurement.count'),record:stockCountSchema,kind:z.enum(['opening','adjustment'])}),
  z.strictObject({type:z.literal('procurement.matched'),record:receiptMatchSchema}),
  z.strictObject({type:z.literal('procurement.movement'),record:procurementMovementSchema}),
  z.strictObject({type:z.literal('procurement.import'),area:procurementAreaSchema,sourceHash:hashSchema})
] as const;
export const procurementEffectSchema=z.discriminatedUnion('type',procurementEffectSchemas);
const viewFields={runId:idSchema};
export const procurementProjectionSchema=z.strictObject({dataset:datasetSchema,orders:z.array(z.strictObject({...viewFields,record:purchaseOrderSchema,status:poStatusSchema,poValueTwd:nonnegativeMoneySchema,openDepositTwd:decimalSchema})),receipts:z.array(z.strictObject({...viewFields,record:receiptSchema})),invoices:z.array(z.strictObject({...viewFields,record:invoiceSchema,openAmountTwd:decimalSchema,matched:z.boolean()})),payments:z.array(supplierPaymentSchema),counts:z.array(z.strictObject({...viewFields,record:stockCountSchema,kind:z.enum(['opening','adjustment'])})),matches:z.array(receiptMatchSchema),history:z.array(z.strictObject({...viewFields,poNumber:poNumberSchema,status:poStatusSchema,effectiveOn:dateSchema})),exceptions:z.array(z.strictObject({reference:text,message:text})),totalPayablesTwd:decimalSchema});
export const inventoryProjectionSchema=z.strictObject({positions:z.array(z.strictObject({sku:text,qtyPieces:wholePiecesSchema,valueTwd:nonnegativeMoneySchema,wacPerPiece:nonnegativeMoneySchema.nullable(),evidenced:z.boolean()})),consumptions:z.array(z.strictObject({orderId:text,sku:text,shipDate:dateSchema,qtyPieces:positivePieces,costTwd:nonnegativeMoneySchema,status:z.enum(['UNPOSTED','POSTED'])})),totalValueTwd:nonnegativeMoneySchema,pendingCogsTwd:nonnegativeMoneySchema,openingRecorded:z.boolean()});
export type ProcurementPayload=z.infer<typeof procurementPayloadSchema>;
export type ProcurementEffect=z.infer<typeof procurementEffectSchema>;
export type ProcurementProjection=z.infer<typeof procurementProjectionSchema>;
export type InventoryProjection=z.infer<typeof inventoryProjectionSchema>;
export type LandedInput=z.infer<typeof landedInputSchema>;
export type LandedLine=z.infer<typeof landedLineSchema>;
export const inventoryOperationSchema=z.strictObject({date:dateSchema,ordinal:z.int().nonnegative(),sku:text,qty:z.string().regex(/^-?(?:0|[1-9]\d*)$/),value:decimalSchema.nullable(),orderId:z.string(),targetPieces:wholePiecesSchema.optional()});
