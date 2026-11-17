import type { z } from 'zod';
import type { MasterProjection } from './schemas/masters';
import { publicMasterPayloadSchema } from './schemas/masters';
export type MasterInput = z.input<typeof publicMasterPayloadSchema>;
export type MasterAction = MasterInput['action'];
export function masterDefaults(action: MasterAction, projection: MasterProjection, requestKey: string, area: 'suppliers' | 'products' | 'channels' | 'accounts' = 'suppliers'): MasterInput {
  const fields = { occurredOn:new Date().toLocaleDateString('en-CA',{timeZone:'Asia/Taipei'}), idempotencyKey:requestKey, expectedHeadHash:null };
  if (action === 'supplier') return {action,...fields,previousRunId:null,record:{supplierRef:'',legalName:'',country:'TW',currency:'TWD',defaultIncoterm:'EXW',paymentTerms:'',canInvoiceToTaxId:'unknown',declarationRef:'',evidenceRef:''}};
  if (action === 'product') return {action,...fields,previousRunId:null,record:{sku:'',name:'',uom:'PC',piecesPerSaleUnit:1,supplierRef:'',ingredientRef:'UNKNOWN',productType:'sellable',evidenceRef:''}};
  if (action === 'channel') return {action,...fields,record:{code:'etsy',name:'Etsy'}};
  if (action === 'business') return {action,...fields,previousRunId:projection.business?.runId ?? null,record:projection.business ? {...projection.business.record,evidenceRef:''} : {tradingName:'',country:'TW',functionalCurrency:'TWD',taxRegime:'unregistered',taxId:'',evidenceRef:''}};
  if (action === 'opening') return {action,...fields,previousRunId:projection.opening?.runId ?? null,record:{mode:'prepare',countedOn:fields.occurredOn,lines:[{sku:projection.products[0]?.record.sku ?? '',condition:'sellable',qtyPieces:'',agreedUnitCostTwd:'0.0000',evidenceRef:''}],evidenceRef:'',founderConfirmed:false}};
  if (action === 'import') return {action,...fields,area,filename:'',csvText:''};
  return {action:'reference',...fields};
}
