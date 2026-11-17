import { z } from 'zod';
import Decimal from '../decimal';
import { journalSchema,type Journal } from '../schemas';
import { decimalSchema,dateSchema } from '../schemas/primitives';
import { positiveAmount,evidenceText } from '../schemas/accounting';
import { accountLeg } from '../accounting';
import { DomainError } from '../errors';
import { exactMoney as money } from '../landed-cost';
const amount=positiveAmount;
export const supplementaryEventSchema=z.discriminatedUnion('eventType',[
 z.strictObject({eventType:z.literal('order.cancelled'),amount,phase:z.enum(['pre','post'])}),
 z.strictObject({eventType:z.literal('order.refunded'),amount,feeRefunds:z.array(z.strictObject({account:z.enum(['6111','6112','6113','6114']),amount}))}),
 z.strictObject({eventType:z.literal('order.ship_cost_accrued'),amount,basisNote:evidenceText}),
 z.strictObject({eventType:z.literal('order.ship_cost_invoiced'),amount,accruedTwd:amount,accrualRef:evidenceText}),
 z.strictObject({eventType:z.literal('order.duty_incurred'),amount:decimalSchema,position:z.enum(['DDP','DDU','unknown'])}),
 z.strictObject({eventType:z.literal('order.duty_invoiced'),amount,accruedTwd:amount,accrualRef:evidenceText}),
 z.strictObject({eventType:z.literal('po.in_transit'),amount}),
 z.strictObject({eventType:z.literal('po.landed_cost_adjusted'),amount,sku:evidenceText,lotRef:evidenceText,onhandRatio:decimalSchema.refine(v=>new Decimal(v).gte(0)&&new Decimal(v).lte(1),'Use a ratio between zero and one.')}),
 z.strictObject({eventType:z.literal('settlement.received'),cashTwd:amount,usdSettled:amount,publicRate:amount,channelRate:z.string().regex(/^\d+(?:\.\d{1,6})?$/),rateSource:z.enum(['stated','derived']),evidenceRef:evidenceText}),
 z.strictObject({eventType:z.literal('settlement.reversed'),originalCarryingTwd:amount,bankReversalTwd:amount,reversalFeeTwd:decimalSchema.refine(v=>new Decimal(v).gte(0))}),
 z.strictObject({eventType:z.literal('order.reprint_issued'),decisionsRef:evidenceText,sku:evidenceText,qtyPieces:z.string().regex(/^[1-9]\d*$/),positionPieces:z.string().regex(/^[1-9]\d*$/),positionValue:amount}),
 z.strictObject({eventType:z.enum(['payment.received','payment.refunded']),amount})
]);
const pair=(d:string,c:string,v:string)=>[accountLeg(d,v,'0'),accountLeg(c,'0',v)];
const variance=(liability:string,expense:string,base:string,actual:string)=>{const delta=new Decimal(actual).minus(base),lines=[accountLeg(liability,base,'0'),accountLeg('2172','0',actual)];if(!delta.isZero())lines.push(accountLeg(expense,delta.gt(0)?money(delta):'0',delta.lt(0)?money(delta.negated()):'0'));return lines;};
export const cancelOrder=(v:string,phase:'pre'|'post')=>pair(phase==='pre'?'2211':'4192','1191',v);
export const refundOrder=(v:string,refunds:readonly {account:string;amount:string}[])=>[...pair('4192','1191',v),...refunds.flatMap(r=>{if(!['6111','6112','6113','6114'].includes(r.account))throw new DomainError('account','Name the original fee category.');return pair('1191',r.account,r.amount);})];
export const accrueShipping=(v:string)=>pair('6131','2191',v);
export const invoiceShipping=(base:string,actual:string)=>variance('2191','6131',base,actual);
export const incurDuty=(v:string,position:'DDP'|'DDU'|'unknown')=>position==='DDP'?pair('6132','2192',v):null;
export const invoiceDuty=(base:string,actual:string)=>variance('2192','6132',base,actual);
export const stockInTransit=(v:string)=>pair('1232','2171',v);
export const adjustLandedCost=(v:string,ratio:string,sku:string)=>{const onhand=money(new Decimal(v).times(ratio));return [accountLeg('1231',onhand,'0',{sku}),accountLeg('5112',money(new Decimal(v).minus(onhand)),'0',{sku}),accountLeg('2172','0',v)];};
export function receiveSettlement(cash:string,usd:string,publicRate:string,channelRate:string,source:'derived'|'stated'){
 if(new Decimal(channelRate).lte(0)||source==='derived'&&!new Decimal(cash).div(usd).toDecimalPlaces(6).eq(channelRate))throw new DomainError('rate','The evidenced applied rate does not match the payout.');
 const carrying=money(new Decimal(usd).times(publicRate)),spread=new Decimal(carrying).minus(cash);if(spread.abs().div(cash).gt('0.10'))throw new DomainError('rate','The spread exceeds the provisional tolerance. Review the rate evidence.');
 const lines=[accountLeg('1121',cash,'0'),accountLeg('1191','0',carrying)];if(!spread.isZero())lines.push(accountLeg('6116',spread.gt(0)?money(spread):'0',spread.lt(0)?money(spread.negated()):'0'));return lines;
}
export function reverseSettlement(original:string,bank:string,fee:string){const delta=new Decimal(bank).minus(original).minus(fee),lines=[accountLeg('1191',original,'0'),accountLeg('1121','0',bank)];if(new Decimal(fee).gt(0))lines.push(accountLeg('6181',fee,'0'));if(!delta.isZero())lines.push(accountLeg('6116',delta.gt(0)?money(delta):'0',delta.lt(0)?money(delta.negated()):'0'));return lines;}
export function reprintCost(qty:string,positionQty:string,positionValue:string,sku:string){if(new Decimal(qty).gt(positionQty))throw new DomainError('stock','Insufficient counted stock for a reprint.');const cost=money(new Decimal(positionValue).times(qty).div(positionQty));return [accountLeg('5111',cost,'0',{sku}),accountLeg('1231','0',cost,{sku,qtyPieces:new Decimal(qty).negated().toFixed(0)})];}
export function supplementaryJournal(raw:unknown,date:string,entryId:string):Journal|null{
 const r=supplementaryEventSchema.parse(raw);dateSchema.parse(date);let lines:Journal['lines']|null;
 switch(r.eventType){case 'order.cancelled':lines=cancelOrder(r.amount,r.phase);break;case 'order.refunded':lines=refundOrder(r.amount,r.feeRefunds);break;case 'order.ship_cost_accrued':lines=accrueShipping(r.amount).map(l=>({...l,memo:`[ESTIMATE] basis: ${r.basisNote}`}));break;case 'order.ship_cost_invoiced':lines=invoiceShipping(r.accruedTwd,r.amount);break;case 'order.duty_incurred':lines=incurDuty(r.amount,r.position);break;case 'order.duty_invoiced':lines=invoiceDuty(r.accruedTwd,r.amount);break;case 'po.in_transit':lines=stockInTransit(r.amount);break;case 'po.landed_cost_adjusted':lines=adjustLandedCost(r.amount,r.onhandRatio,r.sku);break;case 'settlement.received':lines=receiveSettlement(r.cashTwd,r.usdSettled,r.publicRate,r.channelRate,r.rateSource);break;case 'settlement.reversed':lines=reverseSettlement(r.originalCarryingTwd,r.bankReversalTwd,r.reversalFeeTwd);break;case 'order.reprint_issued':lines=reprintCost(r.qtyPieces,r.positionPieces,r.positionValue,r.sku);break;default:throw new DomainError('payment','The local payment gateway is RESERVED.');}
 return lines===null?null:journalSchema.parse({entryId,occurredOn:date,sourceEvent:r.eventType,lines:lines.filter(l=>!new Decimal(l.debit).isZero()||!new Decimal(l.credit).isZero())});
}
