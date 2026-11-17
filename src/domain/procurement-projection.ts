import type { Dataset, Run } from './schemas';
import { procurementProjectionSchema, type ProcurementProjection } from './schemas/procurement';
import Decimal from './decimal';
import { exactMoney } from './landed-cost';

export function projectProcurement(runs:readonly Run[],dataset:Dataset=runs.some(run=>run.effects.some(effect=>effect.type==='dataset.activated'))?'ACTUAL':'SAMPLE',through='9999-12-31'):ProcurementProjection{
  const result:ProcurementProjection={dataset,orders:[],receipts:[],invoices:[],payments:[],counts:[],matches:[],history:[],exceptions:[],totalPayablesTwd:'0.0000' as ProcurementProjection['totalPayablesTwd']};
  for(const run of runs){if(run.dataset!==dataset)continue;for(const effect of run.effects){
    const effective=effect.type==='procurement.po'?effect.record.poDate:effect.type==='procurement.status'?effect.effectiveOn:effect.type==='procurement.receipt'?effect.record.receivedOn:effect.type==='procurement.invoice'?effect.record.invoiceDate:effect.type==='procurement.payment'?effect.record.paidOn:effect.type==='procurement.count'?effect.record.countedAt:effect.type==='procurement.matched'?effect.record.receivedOn:null;
    if(effective&&effective>through)continue;
    if(effect.type==='procurement.po'){result.orders=result.orders.filter(item=>item.record.poNumber!==effect.record.poNumber);result.orders.push({runId:run.runId,record:effect.record,status:effect.record.status,poValueTwd:exactMoney(effect.record.lines.reduce((sum,line)=>sum.plus(line.lineTotalTwd),new Decimal(0))),openDepositTwd:exactMoney('0')});}
    if(effect.type==='procurement.status'){const po=result.orders.find(item=>item.record.poNumber===effect.poNumber);if(po)po.status=effect.status;result.history.push({runId:run.runId,poNumber:effect.poNumber,status:effect.status,effectiveOn:effect.effectiveOn});}
    if(effect.type==='procurement.receipt')result.receipts.push({runId:run.runId,record:effect.record});
    if(effect.type==='procurement.invoice')result.invoices.push({runId:run.runId,record:effect.record,openAmountTwd:effect.record.invoiceTotalTwd,matched:false});
    if(effect.type==='procurement.payment')result.payments.push(effect.record);
    if(effect.type==='procurement.count')result.counts.push({runId:run.runId,record:effect.record,kind:effect.kind});
    if(effect.type==='procurement.matched')result.matches.push(effect.record);
  }}
  for(const po of result.orders){const payments=result.payments.filter(payment=>payment.poNumber===po.record.poNumber);const deposits=payments.reduce((sum,payment)=>payment.paymentKind==='deposit'?sum.plus(payment.amountTwd):['deposit_refund','deposit_forfeit'].includes(payment.paymentKind)?sum.minus(payment.amountTwd):sum,new Decimal(0));const applied=result.matches.filter(match=>match.poNumber===po.record.poNumber).reduce((sum,match)=>sum.plus(match.depositAppliedTwd),new Decimal(0));po.openDepositTwd=exactMoney(deposits.minus(applied));}
  for(const invoice of result.invoices){const match=result.matches.find(item=>item.invoiceNo===invoice.record.invoiceNo);const paid=result.payments.filter(payment=>payment.invoiceNo===invoice.record.invoiceNo&&payment.paymentKind==='balance').reduce((sum,payment)=>sum.plus(payment.amountTwd),new Decimal(0));invoice.matched=Boolean(match);invoice.openAmountTwd=exactMoney(new Decimal(invoice.record.invoiceTotalTwd).minus(match?.depositAppliedTwd??'0').minus(paid));if(match)result.totalPayablesTwd=exactMoney(new Decimal(result.totalPayablesTwd).plus(invoice.openAmountTwd));else result.exceptions.push({reference:invoice.record.invoiceNo,message:'Invoice is not matched and posted. No stock or payable has been created.'});}
  for(const receipt of result.receipts)if(!result.matches.some(match=>match.poNumber===receipt.record.poNumber&&match.receiptNo===receipt.record.receiptNo))result.exceptions.push({reference:`${receipt.record.poNumber}/${receipt.record.receiptNo}`,message:'Receipt needs an agreeing supplier invoice before stock and payable can be booked.'});
  for(const match of result.matches)if(!new Decimal(match.depositAppliedTwd).eq(match.invoiceStatedDepositTwd))result.exceptions.push({reference:match.invoiceNo,message:'The supplier-stated deposit differs from the computed application. The difference is listed, not posted.'});
  return procurementProjectionSchema.parse(result);
}
