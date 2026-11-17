import { approvedChartRows } from '../chart';
import Decimal from '../decimal';
import { journalSchema,journalLineSchema } from '../schemas';
import { exactMoney } from '../landed-cost';
import type { z } from 'zod';
import { supplierPaymentSchema,receiptMatchSchema } from '../schemas/procurement';
import { DomainError } from '../errors';

export function procurementLeg(code:string,debit:string,credit:string){
  const account=approvedChartRows.find(row=>row.account_code===code);if(!account)throw new DomainError('account','The approved account is unavailable.');
  return journalLineSchema.parse({account:{code,name:account.account_name_en},debit,credit,txnAmount:null,txnCurrency:null,fxRateId:null});
}
export function postReceipt(match:z.infer<typeof receiptMatchSchema>){
  const lines:z.infer<typeof journalLineSchema>[]=[];
  for(const line of match.lines){if(!new Decimal(line.goodValue).isZero())lines.push(procurementLeg(line.inventoryAccount,line.goodValue,'0.0000'));if(!new Decimal(line.damagedValue).isZero())lines.push(procurementLeg('5121',line.damagedValue,'0.0000'));}
  if(!new Decimal(match.taxCreditableTwd).isZero())lines.push(procurementLeg('1268',match.taxCreditableTwd,'0.0000'));
  lines.push(procurementLeg('2171','0.0000',match.invoiceTotalTwd));
  if(!new Decimal(match.depositAppliedTwd).isZero())lines.push(procurementLeg('2171',match.depositAppliedTwd,'0.0000'),procurementLeg('1266','0.0000',match.depositAppliedTwd));
  return journalSchema.parse({entryId:match.journalId,occurredOn:match.receivedOn,sourceEvent:'po.received',lines});
}
export function postSupplierPayment(record:z.infer<typeof supplierPaymentSchema>,entryId:string){
  const accounts={deposit:['1266','1121'],balance:['2171','1121'],deposit_refund:['1121','1266'],deposit_forfeit:['6199','1266']} as const;
  const [debit,credit]=accounts[record.paymentKind];
  return journalSchema.parse({entryId,occurredOn:record.paidOn,sourceEvent:'po.paid',lines:[procurementLeg(debit,record.amountTwd,'0.0000'),procurementLeg(credit,'0.0000',record.amountTwd)]});
}
export function postCount(entryId:string,date:string,rows:readonly {value:string;account:string}[],opening:boolean){
  const lines=rows.flatMap(row=>opening?[procurementLeg(row.account,exactMoney(row.value),'0.0000'),procurementLeg('3111','0.0000',exactMoney(row.value))]:[procurementLeg('5121',exactMoney(row.value),'0.0000'),procurementLeg(row.account,'0.0000',exactMoney(row.value))]);
  return journalSchema.parse({entryId,occurredOn:date,sourceEvent:opening?'inventory.opening_counted':'inventory.adjusted',lines});
}
