import { z } from 'zod';
import Decimal from '../decimal';
import codes from '../../../seed/master-codes.json';
import { dateSchema, decimalSchema, hashSchema, idSchema } from './primitives';

const text = (length: number) => z.string().trim().min(1, 'Enter a value.').max(length, 'This value is too long.');
const evidenceSchema = text(255);
const declarationSchema = z.string().max(255).refine((value) => value === '' || (/^compliance\/suppliers\/[^\s]+$/.test(value) && !value.includes('..')), 'Use an evidence reference under compliance/suppliers/.');
export const supplierSchema = z.strictObject({
  supplierRef: z.string().regex(/^SUP-\d{3}$/, 'Use a supplier reference such as SUP-001.'),
  legalName: text(255), country: z.string().refine((value) => codes.countryCodes.includes(value), 'Choose a two-letter country code.'),
  currency: z.string().refine((value) => codes.currencyCodes.includes(value), 'Choose a supported three-letter currency.'),
  defaultIncoterm: z.enum(['EXW','FCA','CPT','CIP','DAP','DPU','DDP','FAS','FOB','CFR','CIF']),
  paymentTerms: text(255), canInvoiceToTaxId: z.enum(['yes','no','unknown']), declarationRef: declarationSchema, evidenceRef: evidenceSchema
});
export const productSchema = z.strictObject({
  sku: text(20), name: text(100), uom: z.literal('PC'),
  piecesPerSaleUnit: z.int('Quantity must be a whole number of pieces.').min(1, 'Each sale unit needs at least one piece.').max(2147483647),
  supplierRef: z.string().regex(/^(?:SUP-\d{3})?$/, 'Choose a supplier or leave it unassigned.'),
  ingredientRef: text(255), productType: z.enum(['sellable','packaging']), evidenceRef: evidenceSchema
}).superRefine((product, context) => {
  const pattern = product.productType === 'sellable' ? /^TS-[A-Z]{2}-\d{3}-[SMLP]$/ : /^PKG-[A-Z]{2,8}-[A-Z]{2,4}$/;
  if (!pattern.test(product.sku)) context.addIssue({ code:'custom', path:['sku'], message:product.productType === 'sellable' ? 'Use a sellable SKU such as TS-FL-001-S.' : 'Use a packaging SKU such as PKG-BOX-TW.' });
  const validIngredient = product.productType === 'packaging' ? product.ingredientRef === 'NOT_APPLICABLE' : product.ingredientRef === 'UNKNOWN' || declarationSchema.safeParse(product.ingredientRef).success && product.ingredientRef !== '';
  if (!validIngredient) context.addIssue({ code:'custom', path:['ingredientRef'], message:product.productType === 'packaging' ? 'Packaging uses NOT_APPLICABLE.' : 'Use UNKNOWN or a supplier compliance evidence reference.' });
});
export const channelSchema = z.strictObject({ code:z.enum(['etsy','instagram']), name:z.enum(['Etsy','Instagram']) }).refine((channel) => channel.name === (channel.code === 'etsy' ? 'Etsy' : 'Instagram'), 'The channel name must match the sales channel.');
export const chartAccountSchema = z.strictObject({
  code:z.string().regex(/^\d{4}$/), nameEn:text(120), nameZh:text(120), type:z.enum(['asset','liability','equity','revenue','cogs','expense','other']),
  statement:z.enum(['BS','PL']), normalBalance:z.enum(['debit','credit']), statutoryCode:z.string().max(40), taxTreatment:z.string().max(20).nullable(),
  taxRegime:z.string().max(20), subledger:z.string().max(20), isReserved:z.boolean(), isContra:z.boolean(), isClosingOnly:z.boolean(), activeFrom:dateSchema.nullable(), activeTo:dateSchema.nullable()
}).refine((account) => account.type !== 'revenue' || Boolean(account.taxTreatment), 'Revenue accounts need a tax treatment.');
export const businessSchema = z.strictObject({ tradingName:text(100), country:z.literal('TW'), functionalCurrency:z.literal('TWD'), taxRegime:z.enum(['unregistered','assessed','general']), taxId:z.string().regex(/^(?:\d{8})?$/, 'Use eight digits, or leave the tax ID blank.'), evidenceRef:evidenceSchema });
export const openingLineSchema = z.strictObject({ sku:text(20), condition:z.enum(['sellable','damaged']), qtyPieces:z.string().regex(/^[1-9]\d{0,9}$/, 'Quantity must be a positive whole number of pieces.'), agreedUnitCostTwd:decimalSchema, evidenceRef:evidenceSchema }).superRefine((line, context) => {
  if (new Decimal(line.agreedUnitCostTwd).isNegative() || line.condition === 'damaged' && !new Decimal(line.agreedUnitCostTwd).isZero()) context.addIssue({code:'custom',path:['agreedUnitCostTwd'],message:'Use a non-negative per-piece cost; damaged pieces must have zero value.'});
});
export const openingPreparationSchema = z.strictObject({ mode:z.enum(['no_stock','prepare']), countedOn:dateSchema, lines:z.array(openingLineSchema).max(500), evidenceRef:evidenceSchema, founderConfirmed:z.boolean().refine((value) => value, 'Confirm that this is your own stock count.') }).superRefine((draft, context) => {
  if (draft.mode === 'no_stock' ? draft.lines.length !== 0 : draft.lines.length === 0) context.addIssue({code:'custom',path:['lines'],message:'A prepared count needs lines; a no-stock declaration must contain no lines.'});
  if (new Set(draft.lines.map((line) => `${line.sku}:${line.condition}`)).size !== draft.lines.length) context.addIssue({code:'custom',path:['lines'],message:'Each SKU and condition may appear only once.'});
});
export const masterAreaSchema = z.enum(['suppliers','products','channels','accounts']);
export const sourceFilenameSchema = z.string().max(100).regex(/^(?:SAMPLE_)?(?:suppliers|products|channels|accounts)_\d{4}-\d{2}-\d{2}\.csv$/, 'Use the dated filename shown in the import guide.');
const requestFields = { occurredOn:dateSchema, idempotencyKey:z.string().min(1).max(255), expectedHeadHash:hashSchema.nullable().default(null) };
const revisionFields = { previousRunId:idSchema.nullable() };
export const supplierPayloadSchema = z.strictObject({ action:z.literal('supplier'), ...requestFields, ...revisionFields, record:supplierSchema });
export const productPayloadSchema = z.strictObject({ action:z.literal('product'), ...requestFields, ...revisionFields, record:productSchema });
export const channelPayloadSchema = z.strictObject({ action:z.literal('channel'), ...requestFields, record:channelSchema });
export const businessPayloadSchema = z.strictObject({ action:z.literal('business'), ...requestFields, ...revisionFields, record:businessSchema });
export const openingPayloadSchema = z.strictObject({ action:z.literal('opening'), ...requestFields, ...revisionFields, record:openingPreparationSchema });
export const referencePayloadSchema = z.strictObject({ action:z.literal('reference'), ...requestFields });
export const importPayloadSchema = z.strictObject({ action:z.literal('import'), ...requestFields, area:masterAreaSchema, filename:sourceFilenameSchema, csvText:z.string().min(1,'Choose a CSV file.').max(524288,'Choose a file smaller than 512 KB.') });
export const publicMasterPayloadSchema = z.discriminatedUnion('action',[supplierPayloadSchema,productPayloadSchema,channelPayloadSchema,businessPayloadSchema,openingPayloadSchema,referencePayloadSchema,importPayloadSchema]);
export const recordMasterPayloadSchema = z.discriminatedUnion('action',[supplierPayloadSchema,productPayloadSchema,channelPayloadSchema,businessPayloadSchema,openingPayloadSchema,referencePayloadSchema]);
export const bootstrapPayloadSchema = z.strictObject({ action:z.literal('bootstrap'), ...requestFields, suppliersCsv:z.string().max(524288), productsCsv:z.string().max(524288) });
export const masterPayloadSchema = z.discriminatedUnion('action',[...publicMasterPayloadSchema.options,bootstrapPayloadSchema]);
export const changeSchema = z.strictObject({ field:text(40), old:z.string(), new:z.string(), evidenceRef:evidenceSchema });
export const masterEffectSchemas = [
  z.strictObject({ type:z.literal('supplier.recorded'), record:supplierSchema, previousRunId:idSchema.nullable(), changes:z.array(changeSchema) }),
  z.strictObject({ type:z.literal('product.recorded'), record:productSchema, previousRunId:idSchema.nullable(), changes:z.array(changeSchema) }),
  z.strictObject({ type:z.literal('channel.recorded'), record:channelSchema }),
  z.strictObject({ type:z.literal('account.recorded'), record:chartAccountSchema }),
  z.strictObject({ type:z.literal('business.recorded'), record:businessSchema, previousRunId:idSchema.nullable() }),
  z.strictObject({ type:z.literal('opening.prepared'), record:openingPreparationSchema, previousRunId:idSchema.nullable(), totalPreparedValueTwd:decimalSchema }),
  z.strictObject({ type:z.literal('masters.imported'), area:masterAreaSchema, filename:sourceFilenameSchema, sourceHash:hashSchema, parsedRows:z.int().nonnegative(), recordsCreated:z.int().nonnegative(), revisionsCreated:z.int().nonnegative() }),
  z.strictObject({ type:z.literal('masters.initialized'), version:z.literal(1) })
] as const;
export const masterEffectSchema = z.discriminatedUnion('type',masterEffectSchemas);
export type Supplier = z.infer<typeof supplierSchema>;
export type Product = z.infer<typeof productSchema>;
export type ChartAccount = z.infer<typeof chartAccountSchema>;
export type MasterPayload = z.infer<typeof masterPayloadSchema>;
export type PublicMasterPayload = z.infer<typeof publicMasterPayloadSchema>;
export type MasterEffect = z.infer<typeof masterEffectSchema>;
const viewFields = { runId:idSchema, createdAt:z.iso.datetime(), sourceFilename:z.string() };
export const supplierViewSchema = z.strictObject({ ...viewFields, record:supplierSchema });
export const productViewSchema = z.strictObject({ ...viewFields, record:productSchema });
export const channelViewSchema = z.strictObject({ ...viewFields, record:channelSchema });
export const accountViewSchema = z.strictObject({ ...viewFields, record:chartAccountSchema });
export const businessViewSchema = z.strictObject({ ...viewFields, record:businessSchema });
export const openingViewSchema = z.strictObject({ ...viewFields, record:openingPreparationSchema, totalPreparedValueTwd:decimalSchema });
export const masterProjectionSchema = z.strictObject({
  dataset:z.enum(['SAMPLE','ACTUAL']), suppliers:z.array(supplierViewSchema), products:z.array(productViewSchema), channels:z.array(channelViewSchema), accounts:z.array(accountViewSchema),
  business:businessViewSchema.nullable(), opening:openingViewSchema.nullable(),
  history:z.array(z.strictObject({ ...viewFields, entity:z.enum(['supplier','product']), key:z.string(), changes:z.array(changeSchema) }))
});
export type MasterProjection = z.infer<typeof masterProjectionSchema>;
export const masterResultSchema = z.strictObject({ ok:z.literal(true), runId:idSchema.nullable(), effects:z.array(masterEffectSchema), summary:z.array(z.string()), duplicate:z.boolean(), preview:z.boolean(), headHash:hashSchema });
