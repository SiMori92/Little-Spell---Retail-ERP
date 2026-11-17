import type { Effect } from './schemas';
import Decimal from './decimal';
import { approvedChartRows } from './chart';
export function financialSummary(effects:readonly Effect[]):string[]{
 return effects.flatMap((effect):string[]=>{
  if(effect.type==='accounting.fact'){const d=effect.record.detail,amount=d.kind==='manual'&&'amount' in d.record?d.record.amount:d.kind==='expense'?d.record.amountTwd:'amount' in d?d.amount:null;return [`Save ${amount?`NT$${amount} as an `:'an '}unposted fact. Review and post it separately before balances change.`];}
  if(effect.type==='accounting.stock-policy')return [`Reorder ${effect.record.sku} below ${effect.record.reorderPoint} pieces. No money moves.`];
  if(effect.type==='accounting.receipt-import')return [`Save ${effect.records} receipts for separate posting review.`];
  if(effect.type==='accounting.inventory-tags')return [`Append sourced product/piece attribution to ${effect.tags.length} journal lines. Original journals stay unchanged.`];
  if(effect.type==='accounting.fx')return [`Record public ${effect.record.currency} rate ${effect.record.rate} TWD for ${effect.record.date}.`];
  if(effect.type==='journal.posted')return effect.entry.lines.filter(line=>!new Decimal(line.debit).isZero()||!new Decimal(line.credit).isZero()).map(line=>{const account=approvedChartRows.find(a=>a.account_code===line.account.code),change=new Decimal(line.debit).minus(line.credit).times(account?.normal_balance==='credit'?-1:1);return `${line.account.name}: ${change.gte(0)?'+':''}NT$${change.toFixed(4)}.`;});
  if(effect.type==='dataset.activated')return ['Activate ACTUAL. SAMPLE facts stay quarantined.'];
  return [];
 });
}
