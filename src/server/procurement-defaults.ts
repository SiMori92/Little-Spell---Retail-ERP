import 'server-only';
import type { z } from 'zod';
import Decimal from '../domain/decimal';
import type { procurementPayloadSchema,ProcurementProjection,InventoryProjection } from '../domain/schemas/procurement';
import type { MasterProjection } from '../domain/schemas/masters';

export function procurementDefaults(action:z.input<typeof procurementPayloadSchema>['action'],state:ProcurementProjection,masters:MasterProjection,inventory:InventoryProjection,key:string,poNumber?:string,invoiceNo?:string,area:'po'|'grn'|'inv'|'pay'|'counts'='po'):z.input<typeof procurementPayloadSchema>{
  const today=new Date().toLocaleDateString('en-CA',{timeZone:'Asia/Taipei'}),fields={occurredOn:today,idempotencyKey:key,expectedHeadHash:null};
  const po=state.orders.find(item=>item.record.poNumber===poNumber);
  if(action==='import')return {action,...fields,area,filename:'',csvText:'',founderConfirmed:false};
  if(action==='po')return {action,...fields,previousRunId:po?.runId??null,record:po?{...structuredClone(po.record),lines:po.record.lines.map(line=>({...line,lineTotalTwd:undefined}))}:{poNumber:'',supplierRef:'',poDate:today,targetDeliveryDate:today,currency:'TWD',paymentTerms:'',incoterm:'EXW',quoteRef:'',status:'draft',lines:[{lineNo:1,sku:'',qtyPieces:'',unitPriceTwd:'',setupChargeTwd:'0.0000',moqPieces:null,artworkRef:'',evidenceRef:''}]}};
  if(action==='receipt')return {action,...fields,record:{poNumber:poNumber??'',receiptNo:'',receivedOn:today,lines:(po?.record.lines??[]).filter(line=>!state.receipts.some(item=>item.record.poNumber===poNumber&&item.record.lines.some(received=>received.lineNo===line.lineNo))).map(line=>({lineNo:line.lineNo,sku:line.sku,qtyGood:line.qtyPieces,qtyDamaged:'0',damagedCredited:false,shortClose:false,shortCloseReason:'',evidenceRef:''}))}};
  if(action==='invoice'){
    const receipt=state.receipts.find(item=>item.record.poNumber===poNumber&&!state.matches.some(match=>match.poNumber===poNumber&&match.receiptNo===item.record.receiptNo));
    const selected=receipt?po?.record.lines.filter(line=>receipt.record.lines.some(received=>received.lineNo===line.lineNo)):po?.record.lines;
    return {action,...fields,record:{invoiceNo:'',guiNo:'',invoiceDate:today,poNumber:poNumber??'',receiptNo:receipt?.record.receiptNo??'',freightTwd:'',taxTwd:'',taxCreditableTwd:'0.0000',invoiceTotalTwd:'',depositAppliedTwd:'',evidenceRef:'',lines:(selected??[]).map(line=>{const received=receipt?.record.lines.find(item=>item.lineNo===line.lineNo);return {lineNo:line.lineNo,sku:line.sku,qtyInvoiced:received?new Decimal(received.qtyGood).plus(received.damagedCredited?'0':received.qtyDamaged).toFixed(0):line.qtyPieces,unitPriceTwd:line.unitPriceTwd,setupChargeTwd:line.setupChargeTwd,statedTaxTwd:null};})}};
  }
  if(action==='payment'){const invoice=state.invoices.find(item=>item.record.invoiceNo===invoiceNo);return {action,...fields,record:{paymentRef:'',paidOn:today,supplierRef:po?.record.supplierRef??'',poNumber:poNumber??'',invoiceNo:invoiceNo??'',paymentKind:invoice?'balance':'deposit',amountTwd:invoice?.openAmountTwd??'',bankAccount:'1121',bankRef:'',evidenceRef:''}};}
  const prepared=masters.opening?.record;
  return {action:'count',...fields,founderConfirmed:false,record:{countedAt:inventory.openingRecorded?today:prepared?.countedOn??today,evidenceRef:'',lines:masters.products.map(({record})=>{const position=inventory.positions.find(item=>item.sku===record.sku),draft=prepared?.lines.find(line=>line.sku===record.sku&&line.condition==='sellable');return {sku:record.sku,qtyPieces:inventory.openingRecorded?position?.qtyPieces??'':draft?.qtyPieces??'',agreedUnitCostTwd:inventory.openingRecorded?position?.wacPerPiece??'0.0000':draft?.agreedUnitCostTwd??'',condition:'sellable'};})}};
}
