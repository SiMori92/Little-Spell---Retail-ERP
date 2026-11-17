import chart from '../../../seed/coa_snapshot.json';
import Decimal from '../decimal';
import { dateSchema, journalSchema, journalLineSchema } from '../schemas';
import { sellOrderSchema, saleFxSchema } from '../schemas/selling';
import { DomainError } from '../errors';

function leg(code:string,side:'debit'|'credit',amount:string,transaction: {amount:string;rateId:string}|null=null) {
  const account=chart.rows.find(row=>row.account_code===code);if(!account)throw new DomainError('account','An approved account is unavailable.');
  return journalLineSchema.parse({account:{code,name:account.account_name_en},debit:side==='debit'?amount:'0.0000',credit:side==='credit'?amount:'0.0000',txnAmount:transaction?.amount??null,txnCurrency:transaction?'USD':null,fxRateId:transaction?.rateId??null});
}
export function placeOrder(orderInput:unknown,fxInput:unknown,entryId:string) {
  const order=sellOrderSchema.parse(orderInput),fx=saleFxSchema.parse(fxInput);if(fx.date!==order.orderDate)throw new DomainError('fx','Use the public rate on the order date.');
  const amount=order.discountFundedBy==='seller'?order.buyerPaid:order.gross;
  const value=new Decimal(amount).times(fx.rate).toFixed(4),transaction={amount,rateId:fx.id};
  return journalSchema.parse({entryId,occurredOn:order.orderDate,sourceEvent:'order.placed',lines:[leg('1191','debit',value,transaction),leg('2211','credit',value,transaction)]});
}
export function dispatchOrder(orderInput:unknown,fxInput:unknown,shipDate:string,entryId:string) {
  const order=sellOrderSchema.parse(orderInput),fx=saleFxSchema.parse(fxInput);dateSchema.parse(shipDate);
  if(shipDate<order.orderDate||fx.date!==order.orderDate)throw new DomainError('shipDate','Dispatch needs a valid ship date and the original deposit public rate.');
  if(!['TW','US','JP','FR','GB','AU'].includes(order.country))throw new DomainError('country','Resolve destination tax treatment before posting.');
  const deposit=placeOrder(order,fx,entryId).lines[0]!.debit;
  const product=order.lines.reduce((sum,line)=>sum.plus(new Decimal(line.qtySaleUnits).times(line.unitPrice)),new Decimal(0)).times(fx.rate).toFixed(4);
  const shipping=new Decimal(order.shipping).plus(order.shippingDiscount).times(fx.rate).toFixed(4);
  const discount=new Decimal(order.discount).times(fx.rate).toFixed(4);
  const lines=[leg('2211','debit',deposit),leg(order.country==='TW'?'4112':'4111','credit',product)];
  if(!new Decimal(shipping).isZero())lines.push(leg(order.country==='TW'?'4182':'4181','credit',shipping));
  if(order.discountFundedBy==='seller'&&!new Decimal(discount).isZero())lines.push(leg('4191','debit',discount));
  return journalSchema.parse({entryId,occurredOn:shipDate,sourceEvent:'order.shipped',lines});
}
