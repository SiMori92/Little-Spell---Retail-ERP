import 'server-only';
import type { z } from 'zod';
import type { sellingPayloadSchema, SellingProjection } from '../domain/schemas/selling';
import { headerHashes } from '../domain/selling-csv';
import { DomainError } from '../domain/errors';

export function sellingDefaults(action:z.input<typeof sellingPayloadSchema>['action'],projection:SellingProjection,idempotencyKey:string,orderId?:string):z.input<typeof sellingPayloadSchema> {
  const today=new Date().toLocaleDateString('en-CA',{timeZone:'Asia/Taipei'});
  const fields={occurredOn:today,idempotencyKey,expectedHeadHash:null};
  if(action==='etsy')return {action,...fields,orderFilename:'',statementFilename:'',ordersCsv:'',statementCsv:'',couponRules:[]};
  if(action==='ig-import')return {action,...fields,filename:'',csvText:''};
  if(action==='verify-etsy')return {action,...fields,...headerHashes,evidenceRef:'',founderConfirmed:false};
  if(action==='dispatch'){const order=projection.orders.find(item=>item.record.orderId===orderId);if(!order)throw new DomainError('orderId','Choose a recorded order to dispatch.');return {action,...fields,orderId:order.record.orderId,previousRunId:order.runId,shipDate:today,trackingRef:'',evidenceRef:''};}
  return {action:'deal',...fields,previousRunId:null,record:{dealId:'',customerRef:'',status:'enquiry',enquiryAt:today,quotedAt:null,quoteTwd:null,followUpOn:null,lostReason:'',lines:[{sku:'',qtySaleUnits:null,unitPriceTwd:null}],shippingTwd:null,shipCountry:'',paidAt:null,walletTxnId:'',shipDate:null,consentMarketing:'',journeySent:'none',evidenceRef:''}};
}
