import { createHash } from 'node:crypto';
import { z } from 'zod';
import Decimal from './decimal';
import { parseCsv } from './csv';
import { DomainError } from './errors';
import { containsContactDetails } from './privacy';
import countries from '../../seed/etsy-country-names.json';
import orderHeader from '../../seed/schemas/etsy_orderitems_header_v1.json';
import statementHeader from '../../seed/schemas/etsy_statement_header_v1.json';
import igHeader from '../../seed/schemas/ig_deals_header_v2.json';
import { dateSchema, decimalSchema } from './schemas/primitives';
import { dealSchema, sellOrderSchema, statementTypeSchema, statementRowSchema, type SellOrder, type Deal, type SellingPayload } from './schemas/selling';

export const sellingHeaders = {orderitems:orderHeader,statement:statementHeader,instagram:igHeader};
export const shaText = (text:string) => createHash('sha256').update(text).digest('hex');
export const headerHashes = {orderHeaderHash:shaText(JSON.stringify(orderHeader.header)),statementHeaderHash:shaText(JSON.stringify(statementHeader.header))};
export function refuseSelling(field:string,message:string):never { throw new DomainError(field,message); }
export function exactRows(source:string,header:readonly string[]): Record<string,string>[] {
  const [observed,...rows] = parseCsv(source);
  if (!observed || observed.length!==header.length || observed.some((column,index)=>column!==header[index])) refuseSelling('csvText','Use the exact current CSV header and column order. Instagram requires v2 sale-unit quantities.');
  if (!rows.length) refuseSelling('csvText','Add at least one row below the header.');
  return rows.map(cells=>{if(cells.length!==header.length)refuseSelling('csvText','A row has the wrong number of cells. Nothing was imported.');return Object.fromEntries(header.map((key,index)=>[key,cells[index]!.trim()]));});
}
function sourceCsv(header:readonly string[],rows:readonly Record<string,string>[]):string {
  const cell=(value:string)=>/[",\r\n]/.test(value)?`"${value.replaceAll('"','""')}"`:value;
  return [header.map(cell).join(','),...rows.map(row=>header.map(key=>cell(row[key]??'')).join(','))].join('\n')+'\n';
}
const retainedOrderColumns = new Set(['Sale Date','Quantity','Price','Coupon Code','Discount Amount','Shipping Discount','Order Shipping','Order Sales Tax','Item Total','Currency','Transaction ID','Listing ID','Date Shipped','Ship Country','Order ID','Listings Type','Payment Type','SKU']);
export function normalizeSelling(input:SellingPayload):SellingPayload {
  if(input.action!=='etsy')return structuredClone(input);
  const orders=exactRows(input.ordersCsv,orderHeader.header).map(row=>Object.fromEntries(orderHeader.header.map(key=>[key,retainedOrderColumns.has(key)?row[key]??'':''])));
  const statements=exactRows(input.statementCsv,statementHeader.header).map(row=>{
    const ref=row.Type==='Listing Fee'?row.Info?.match(/Listing #(\d+)/)?.[1]:row.Info?.match(/Order #(\d+)/)?.[1];
    if(row.Type!=='Deposit'&&!ref)refuseSelling('statementCsv','A statement row is missing its order or listing reference.');
    return {...row,Title:'',Info:row.Type==='Deposit'?'Deposit':`${row.Type==='Listing Fee'?'Listing':'Order'} #${ref}`};
  });
  return {...input,ordersCsv:sourceCsv(orderHeader.header,orders),statementCsv:sourceCsv(statementHeader.header,statements)};
}
export function sourcePeriod(filename:string,kind:'orderitems'|'statement'|'ig_deals',dataset:'SAMPLE'|'ACTUAL'):string {
  const prefix=dataset==='SAMPLE'?'SAMPLE_':'';
  const type=kind==='ig_deals'?kind:`etsy_${kind}`;
  const match=filename.match(new RegExp(`^${prefix}${type}_(\\d{4}-(?:0[1-9]|1[0-2]))${dataset==='SAMPLE'&&kind!=='ig_deals'?'(?:_fixture)?':''}\\.csv$`));
  if(!match)refuseSelling('filename','Use the prescribed monthly filename for the current dataset.');
  return match[1]!;
}
export function sourceMoney(raw:string|undefined,nullable=false):z.infer<typeof decimalSchema>|null {
  if(nullable&&(raw===''||raw==='--'))return null;
  if(!raw||!/^[-]?(?:0|[1-9]\d{0,11})(?:\.\d{1,2})?$/.test(raw))refuseSelling('csvText','Etsy money must be a decimal amount with at most two decimal places; missing values are not zero.');
  return decimalSchema.parse(new Decimal(raw).toFixed(4));
}
export function sourceDate(raw:string,kind:'orderitems'|'statement'):string {
  const monthNames=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  const match=kind==='orderitems'?raw.match(/^(\d{1,2})\/(\d{1,2})\/(\d{2})$/):raw.match(/^([A-Z][a-z]{2}) (\d{1,2}), (\d{4})$/);
  if(!match)refuseSelling('csvText','Use the date format in the original Etsy export.');
  const month=kind==='orderitems'?match[1]!.padStart(2,'0'):String(monthNames.indexOf(match[1]!)+1).padStart(2,'0');
  return dateSchema.parse(`${kind==='orderitems'?`20${match[3]}`:match[3]}-${month}-${match[2]!.padStart(2,'0')}`);
}
export function parseOrders(input:Extract<SellingPayload,{action:'etsy'}>):SellOrder[] {
  const grouped=new Map<string,Record<string,string>[]>(),transactions=new Set<string>();
  for(const row of exactRows(input.ordersCsv,orderHeader.header)) {
    if(transactions.has(row['Transaction ID']!))refuseSelling('ordersCsv','A transaction identifier repeats. Nothing was imported.');
    transactions.add(row['Transaction ID']!);
    if(row['Listings Type']!=='Physical'||row['Payment Type']!=='Etsy Payments'||row.Currency!=='USD')refuseSelling('ordersCsv','This listing, payment, or currency shape is not supported by the verified contract.');
    const list=grouped.get(row['Order ID']!)??[];list.push(row);grouped.set(row['Order ID']!,list);
  }
  return [...grouped].map(([orderId,rows])=>{
    const first=rows[0]!;
    for(const field of ['Sale Date','Currency','Coupon Code','Order Shipping','Shipping Discount','Order Sales Tax','Ship Country','Date Shipped'])if(rows.some(row=>row[field]!==first[field]))refuseSelling('ordersCsv','Order-level details conflict between item rows.');
    const orderDate=sourceDate(first['Sale Date']!,'orderitems');
    const lines=rows.sort((left,right)=>left.SKU!.localeCompare(right.SKU!)||left['Transaction ID']!.localeCompare(right['Transaction ID']!)).map(row=>({transactionId:row['Transaction ID'],sku:row.SKU,listingId:row['Listing ID'],qtySaleUnits:row.Quantity,unitPrice:sourceMoney(row.Price),discount:sourceMoney(row['Discount Amount']),itemTotal:sourceMoney(row['Item Total'])}));
    const shipping=sourceMoney(first['Order Shipping'])!,shippingDiscount=sourceMoney(first['Shipping Discount'])!;
    const gross=lines.reduce((sum,line)=>sum.plus(new Decimal(line.qtySaleUnits!).times(line.unitPrice!)),new Decimal(shipping).plus(shippingDiscount));
    const discount=lines.reduce((sum,line)=>sum.plus(line.discount!),new Decimal(shippingDiscount));
    const rules=input.couponRules.filter(rule=>rule.code.trim().toUpperCase()===first['Coupon Code']!.toUpperCase()&&(!rule.validFrom||rule.validFrom<=orderDate)&&(!rule.validTo||rule.validTo>=orderDate));
    if(!discount.isZero()&&rules.length!==1)refuseSelling('couponRules','Each discounted order needs exactly one evidenced coupon-funder rule valid on its order date.');
    const country=countries[first['Ship Country'] as keyof typeof countries];
    if(!country)refuseSelling('ordersCsv','This destination needs a country/tax-treatment ruling before import.');
    return sellOrderSchema.parse({orderId,orderDate,currency:'USD',country,couponCode:first['Coupon Code'],discountFundedBy:discount.isZero()?'none':rules[0]!.fundedBy,gross:gross.toFixed(4),discount:discount.toFixed(4),buyerPaid:gross.minus(discount).toFixed(4),shipping,shippingDiscount,platformTax:sourceMoney(first['Order Sales Tax']),importedShipDate:first['Date Shipped']?sourceDate(first['Date Shipped'],'orderitems'):null,lines});
  });
}
export function parseStatement(input:Extract<SellingPayload,{action:'etsy'}>,period:string) {
  const occurrences=new Map<string,number>();
  const rows=exactRows(input.statementCsv,statementHeader.header).map(row=>{
    const type=statementTypeSchema.parse(row.Type),occurredOn=sourceDate(row.Date!,'statement');
    if(occurredOn.slice(0,7)!==period)refuseSelling('statementCsv','A statement row date is outside its filename month.');
    if(row.Currency!=='USD'||!['','--'].includes(row['Tax Details']!))refuseSelling('statementCsv','This statement currency or tax-detail shape requires a ruling.');
    const amount=sourceMoney(row.Amount,true),fee=sourceMoney(row['Fees & Taxes'],true),net=sourceMoney(row.Net)!;
    if((amount===null)===(fee===null)||!new Decimal(net).eq(amount??fee!))refuseSelling('statementCsv','Amount and Fees & Taxes must be mutually exclusive and agree with Net.');
    if(['Sale','Deposit'].includes(type)?amount===null:fee===null||new Decimal(fee).gte(0))refuseSelling('statementCsv','Sale/deposit amounts and negative fee columns do not match their row type.');
    if(type==='Sale'&&new Decimal(net).lte(0)||type==='Deposit'&&new Decimal(net).gte(0))refuseSelling('statementCsv','A sale must be positive. A positive or zero deposit requires separate reversal evidence.');
    const minor=(value:string|null)=>value===null?'null':new Decimal(value).times(100).toFixed(0);
    const encoded=`[${[JSON.stringify(period),JSON.stringify(occurredOn),JSON.stringify(type),JSON.stringify(row.Info),JSON.stringify('USD'),minor(amount),minor(fee),minor(net)].join(',')}]`;
    const hash=shaText(encoded),count=(occurrences.get(hash)??0)+1;occurrences.set(hash,count);
    return statementRowSchema.parse({key:`stmt|etsy|${period}|${hash.slice(0,16)}|#${count}`,occurredOn,type,currency:'USD',amount,fee,net,orderRef:row.Info!.match(/Order #(\d+)/)?.[1]??'',listingRef:row.Info!.match(/Listing #(\d+)/)?.[1]??''});
  });
  const keys=rows.map(row=>row.key).sort();
  return {rows,multisetDigest:shaText(`[${keys.map(key=>JSON.stringify(key)).join(', ')}]`)};
}
export function parseDeals(csvText:string):Deal[] {
  const grouped=new Map<string,Record<string,string>[]>();
  for(const row of exactRows(csvText,igHeader.header)){if(Object.values(row).some(containsContactDetails))refuseSelling('csvText','Keep buyer contact details out of deal files; use anonymous references.');const list=grouped.get(row.deal_id!)??[];list.push(row);grouped.set(row.deal_id!,list);}
  const optional=(value:string|undefined)=>value||null;
  return [...grouped].map(([dealId,rows])=>{
    rows.sort((left,right)=>parseInt(left.line_no!,10)-parseInt(right.line_no!,10));
    if(rows.some((row,index)=>row.line_no!==String(index+1)))refuseSelling('csvText','Deal line numbers must start at one, with no gaps or duplicates.');
    for(const field of igHeader.header.filter(key=>!['line_no','sku','qty_sale_units','unit_price_twd'].includes(key)))if(rows.some(row=>row[field]!==rows[0]![field]))refuseSelling('csvText','Deal-level details conflict between lines.');
    const row=rows[0]!;
    return dealSchema.parse({dealId,customerRef:row.customer_ref,status:row.status,enquiryAt:row.enquiry_at,quotedAt:optional(row.quoted_at),quoteTwd:optional(row.quote_twd),followUpOn:optional(row.follow_up_on),lostReason:row.lost_reason,lines:rows.map(line=>({sku:line.sku,qtySaleUnits:optional(line.qty_sale_units),unitPriceTwd:optional(line.unit_price_twd)})),shippingTwd:optional(row.shipping_charged_twd),shipCountry:row.ship_country,paidAt:optional(row.paid_at),walletTxnId:row.wallet_txn_id,shipDate:optional(row.ship_date),consentMarketing:row.consent_marketing,journeySent:row.journey_sent,evidenceRef:row.evidence_ref});
  });
}
