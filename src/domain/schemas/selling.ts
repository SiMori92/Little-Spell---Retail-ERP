import { z } from 'zod';
import Decimal from '../decimal';
import codes from '../../../seed/master-codes.json';
import { dateSchema, decimalSchema, hashSchema, idSchema, datasetSchema } from './primitives';

const text = z.string().trim().min(1, 'Enter a value.').max(255);
export const piecesSchema = z.string().regex(/^[1-9]\d{0,9}$/, {error:'Quantity must be a positive whole number of sale units.',abort:true});
const nonnegative = decimalSchema.refine((value) => !new Decimal(value).isNegative(), 'Use a non-negative amount.').transform(value=>decimalSchema.parse(new Decimal(value).toFixed(4)));
const positive = decimalSchema.refine((value) => new Decimal(value).gt(0), 'Use an amount greater than zero.').transform(value=>decimalSchema.parse(new Decimal(value).toFixed(4)));
export const orderLineSchema = z.strictObject({ transactionId:z.string().regex(/^\d+$/).max(64), sku:text, listingId:z.string().max(64), qtySaleUnits:piecesSchema, unitPrice:nonnegative, discount:nonnegative, itemTotal:nonnegative }).refine((line) => new Decimal(line.qtySaleUnits).times(line.unitPrice).minus(line.discount).eq(line.itemTotal), 'The item total must equal quantity times price less its discount.');
export const sellOrderSchema = z.strictObject({ orderId:z.string().regex(/^\d+$/).max(64), orderDate:dateSchema, currency:z.literal('USD'), country:z.string().regex(/^[A-Z]{2}$/), couponCode:z.string().max(40), discountFundedBy:z.enum(['none','seller','platform']), gross:nonnegative, discount:nonnegative, buyerPaid:nonnegative, shipping:nonnegative, shippingDiscount:nonnegative, platformTax:nonnegative, importedShipDate:dateSchema.nullable(), lines:z.array(orderLineSchema).min(1).max(500) }).superRefine((order, context) => {
  const product = order.lines.reduce((sum,line) => sum.plus(new Decimal(line.qtySaleUnits).times(line.unitPrice)), new Decimal(0));
  const discount = order.lines.reduce((sum,line) => sum.plus(line.discount), new Decimal(order.shippingDiscount));
  if (!product.plus(order.shipping).plus(order.shippingDiscount).eq(order.gross) || !discount.eq(order.discount) || !new Decimal(order.gross).minus(order.discount).eq(order.buyerPaid)) context.addIssue({code:'custom',message:'The order totals do not agree.'});
  if (new Decimal(order.discount).isZero() !== (order.discountFundedBy === 'none')) context.addIssue({code:'custom',message:'Record who funds this discount.'});
  if (order.importedShipDate && order.importedShipDate < order.orderDate) context.addIssue({code:'custom',message:'The ship date cannot be before the order date.'});
  if (new Set(order.lines.map(line=>line.transactionId)).size !== order.lines.length) context.addIssue({code:'custom',message:'An order repeats a transaction identifier.'});
});
export const statementTypeSchema = z.enum(['Sale','Transaction Fee','Processing Fee','Offsite Ads Fee','Regulatory Operating Fee','Listing Fee','Deposit']);
export const statementRowSchema = z.strictObject({ key:text, occurredOn:dateSchema, type:statementTypeSchema, currency:z.literal('USD'), amount:decimalSchema.nullable(), fee:decimalSchema.nullable(), net:decimalSchema, orderRef:z.string().regex(/^\d*$/), listingRef:z.string().regex(/^\d*$/) });
export const statementSchema = z.strictObject({ period:z.string().regex(/^\d{4}-(?:0[1-9]|1[0-2])$/), multisetDigest:hashSchema, rows:z.array(statementRowSchema).min(1).max(5000), residual:decimalSchema, compositionResolved:z.boolean() });
export const igStatusSchema = z.enum(['enquiry','quoted','paid','shipped','followed_up','lost']);
export const dealLineSchema = z.strictObject({ sku:z.string().max(20), qtySaleUnits:piecesSchema.nullable(), unitPriceTwd:positive.nullable() });
export const dealSchema = z.strictObject({ dealId:z.string().regex(/^IG-\d{6}-\d{3}$/, 'Use an identifier such as IG-202611-001.'), customerRef:z.string().regex(/^C-\d{4,}$/, 'Use an anonymous customer reference such as C-0001.').max(32), status:igStatusSchema, enquiryAt:dateSchema, quotedAt:dateSchema.nullable(), quoteTwd:positive.nullable(), followUpOn:dateSchema.nullable(), lostReason:z.enum(['','no_reply','price','shipping_cost','out_of_stock','other']), lines:z.array(dealLineSchema).min(1).max(500), shippingTwd:nonnegative.nullable(), shipCountry:z.string().max(2), paidAt:dateSchema.nullable(), walletTxnId:z.string().max(100), shipDate:dateSchema.nullable(), consentMarketing:z.enum(['','yes','no']), journeySent:z.enum(['none','d0','d10','d30']), evidenceRef:text }).superRefine((deal, context) => {
  const issue = (field:string,message:string) => context.addIssue({code:'custom',path:[field],message});
  if (deal.dealId.slice(3,9) !== deal.enquiryAt.slice(0,7).replace('-','')) issue('dealId','The deal identifier must match the enquiry month.');
  const rank = igStatusSchema.options.indexOf(deal.status);
  if (rank >= 1 && rank <= 4 && (!deal.quotedAt || !deal.quoteTwd)) issue('quoteTwd','Record a quote date and positive quote before continuing.');
  if (['enquiry','quoted'].includes(deal.status) && !deal.followUpOn) issue('followUpOn','Choose the next follow-up date for this open deal.');
  if ((deal.status === 'lost') !== Boolean(deal.lostReason)) issue('lostReason','Choose a lost reason only when marking a deal lost.');
  if (['paid','shipped','followed_up'].includes(deal.status)) {
    if (!deal.paidAt || !deal.walletTxnId || deal.shippingTwd === null || !codes.countryCodes.includes(deal.shipCountry)) issue('paidAt','Record the payment date, wallet reference, shipping charge, and destination country.');
    if (deal.lines.some(line=>!line.sku || line.qtySaleUnits === null || line.unitPriceTwd === null)) issue('lines','Paid deals need a product, positive whole sale units, and a positive price on every line.');
  }
  if (['shipped','followed_up'].includes(deal.status) && !deal.shipDate) issue('shipDate','Record the dispatch date before marking this deal shipped.');
  let previous = deal.enquiryAt;
  for (const [field,value] of [['quotedAt',deal.quotedAt],['paidAt',deal.paidAt],['shipDate',deal.shipDate]] as const) if (value) { if (value < previous) issue(field,'Dates must follow enquiry, quote, payment, then dispatch.'); previous=value; }
  if (deal.followUpOn && deal.followUpOn < deal.enquiryAt) issue('followUpOn','The follow-up date cannot be before the enquiry.');
});
export const couponRuleSchema = z.strictObject({ code:text, fundedBy:z.enum(['seller','platform']), validFrom:dateSchema.nullable(), validTo:dateSchema.nullable(), evidenceRef:text }).refine(rule=>!rule.validFrom || !rule.validTo || rule.validFrom<=rule.validTo,'Coupon validity dates are reversed.');
const request = { occurredOn:dateSchema, idempotencyKey:text, expectedHeadHash:hashSchema.nullable().default(null) };
const csv = z.string().min(1,'Choose a CSV file.').max(524288,'Choose a CSV smaller than 512 KB.');
export const etsyPayloadSchema = z.strictObject({ action:z.literal('etsy'), ...request, orderFilename:z.string().max(100), statementFilename:z.string().max(100), ordersCsv:csv, statementCsv:csv, couponRules:z.array(couponRuleSchema).max(500) });
export const igImportPayloadSchema = z.strictObject({ action:z.literal('ig-import'), ...request, filename:z.string().max(100), csvText:csv });
export const dealPayloadSchema = z.strictObject({ action:z.literal('deal'), ...request, previousRunId:idSchema.nullable(), record:dealSchema });
export const dispatchPayloadSchema = z.strictObject({ action:z.literal('dispatch'), ...request, orderId:text, previousRunId:idSchema, shipDate:dateSchema, trackingRef:z.string().max(100), evidenceRef:text });
export const contractPayloadSchema = z.strictObject({ action:z.literal('verify-etsy'), ...request, orderHeaderHash:hashSchema, statementHeaderHash:hashSchema, evidenceRef:text, founderConfirmed:z.boolean().refine(value=>value,'Confirm your own header review.') });
export const sellingPayloadSchema = z.discriminatedUnion('action',[etsyPayloadSchema,igImportPayloadSchema,dealPayloadSchema,dispatchPayloadSchema,contractPayloadSchema]);
export const shipmentSchema = z.strictObject({ orderId:text, shipDate:dateSchema, trackingRef:z.string().max(100), evidenceRef:text, lines:z.array(z.strictObject({sku:text,qtyPieces:piecesSchema})).min(1) });
const eventFields={eventId:hashSchema,entityRef:text,occurredOn:dateSchema,currency:z.literal('USD'),amount:decimalSchema.nullable(),status:z.literal('UNPOSTED')};
export const saleEventSchema = z.discriminatedUnion('eventType',[
  z.strictObject({...eventFields,eventType:z.literal('order.placed'),payload:z.strictObject({discount:decimalSchema,discount_funded_by:z.enum(['seller','platform','none']),tax_remitted_by_platform:decimalSchema,tax_treatment_hint:z.enum(['domestic','export'])})}),
  z.strictObject({...eventFields,eventType:z.literal('order.shipped'),payload:z.strictObject({shipDate:dateSchema})}),
  z.strictObject({...eventFields,eventType:z.literal('order.cogs_relieved'),payload:z.strictObject({cost_basis:z.literal('provisional')})}),
  z.strictObject({...eventFields,eventType:z.literal('order.fees_assessed'),payload:z.strictObject({order_id:text,fee_components:z.array(z.strictObject({code:z.enum(['transaction_fee','payment_processing_fee','offsite_ads_fee','regulatory_operating_fee']),amount:decimalSchema})).min(1)})}),
  z.strictObject({...eventFields,eventType:z.literal('cost.recorded'),payload:z.strictObject({category:z.literal('platform_listing_fee'),settled_via:z.literal('etsy_rail'),listing_id:text})}),
  z.strictObject({...eventFields,eventType:z.literal('settlement.received'),payload:z.strictObject({composition_unresolved:z.boolean(),covers_order_ids:z.array(text),value_date:dateSchema.nullable(),bank_credit_ref:text.nullable(),bank_account_ref_partial:text.nullable()})})
]);
export const saleFxSchema = z.strictObject({id:text,date:dateSchema,currency:z.literal('USD'),rate:z.string().regex(/^(?:0|[1-9]\d{0,7})(?:\.\d{1,6})?$/,{error:'Use a valid evidenced public rate.',abort:true}).refine(value=>new Decimal(value).gt(0),'Use a positive evidenced public rate.'),source:z.literal('public'),evidenceRef:text});
export const sellingEffectSchemas = [
  z.strictObject({type:z.literal('selling.order'),record:sellOrderSchema}),
  z.strictObject({type:z.literal('selling.statement'),record:statementSchema}),
  z.strictObject({type:z.literal('selling.deal'),record:dealSchema,previousRunId:idSchema.nullable(),effectiveOn:dateSchema}),
  z.strictObject({type:z.literal('selling.shipment'),record:shipmentSchema}),
  z.strictObject({type:z.literal('selling.event'),record:saleEventSchema}),
  z.strictObject({type:z.literal('selling.verified'),orderHeaderHash:hashSchema,statementHeaderHash:hashSchema,evidenceRef:text}),
  z.strictObject({type:z.literal('selling.import'),area:z.enum(['etsy','instagram']),sourceHash:hashSchema,recordsCreated:z.int().nonnegative(),warnings:z.array(z.string())})
] as const;
export const sellingEffectSchema = z.discriminatedUnion('type',sellingEffectSchemas);
export const sellingProjectionSchema = z.strictObject({dataset:datasetSchema,orders:z.array(z.strictObject({runId:idSchema,record:sellOrderSchema})),statements:z.array(statementSchema),deals:z.array(z.strictObject({runId:idSchema,record:dealSchema})),shipments:z.array(shipmentSchema),events:z.array(saleEventSchema),history:z.array(z.strictObject({runId:idSchema,createdAt:z.iso.datetime(),record:dealSchema,effectiveOn:dateSchema})),verified:z.boolean()});
export const sellingResultSchema = z.strictObject({ok:z.literal(true),runId:idSchema.nullable(),effects:z.array(sellingEffectSchema),summary:z.array(z.string()),warnings:z.array(z.string()),blockers:z.array(z.string()),duplicate:z.boolean(),preview:z.boolean(),headHash:hashSchema});
export type SellingPayload = z.infer<typeof sellingPayloadSchema>;
export type SellingEffect = z.infer<typeof sellingEffectSchema>;
export type SellingProjection = z.infer<typeof sellingProjectionSchema>;
export type SellOrder = z.infer<typeof sellOrderSchema>;
export type Deal = z.infer<typeof dealSchema>;
