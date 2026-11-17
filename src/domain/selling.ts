import { canonical, digest } from './canonical';
import type { z } from 'zod';
import Decimal from './decimal';
import { projectMasters } from './master-projection';
import { projectSelling } from './selling-projection';
import { projectInventory } from './inventory-projection';
import { headerHashes, normalizeSelling, parseDeals, parseOrders, parseStatement, refuseSelling as refuse, shaText, sourcePeriod } from './selling-csv';
import { sellingPayloadSchema, igStatusSchema, shipmentSchema, statementSchema, saleEventSchema, type Deal, type SellOrder, type SellingEffect, type SellingPayload } from './schemas/selling';
import { runSchema,type Candidate,type Run } from './schemas';

export function sellingBlockers(input:SellingPayload,runs:readonly Run[]):string[] {
  const blockers:string[]=[];
  if(input.action==='etsy'&&!projectSelling(runs).verified)blockers.push('Etsy headers are unverified. Record your evidenced header review before confirming this import.');
  return blockers;
}
export function planSelling(raw:unknown,runs:readonly Run[],preview=false):Candidate {
  const input=normalizeSelling(sellingPayloadSchema.parse(raw));
  const projection=projectSelling(runs),masters=projectMasters(runs),dataset=projection.dataset;
  const key=input.action==='etsy'?`selling-etsy:${dataset}:${digest({orders:input.ordersCsv,statement:input.statementCsv,coupons:input.couponRules})}`:input.action==='ig-import'?`selling-ig:${dataset}:${shaText(input.csvText)}`:`selling-record:${input.idempotencyKey}`;
  const existing=runs.find(run=>run.idempotencyKey===key);
  if(existing){if(!['etsy','ig-import'].includes(input.action)&&canonical(input)!==canonical(existing.input))refuse('idempotencyKey','This request key was already used. Reopen the latest record.');return structuredClone({kind:existing.kind,dataset:existing.dataset,occurredOn:existing.occurredOn,input:existing.input,effects:existing.effects,idempotencyKey:existing.idempotencyKey});}
  if(input.expectedHeadHash&&input.expectedHeadHash!==(runs.at(-1)?.hash??'0'.repeat(64)))refuse('expectedHeadHash','Records changed after preview. Preview again before confirming.');
  const blockers=sellingBlockers(input,runs);if(!preview&&blockers.length)refuse('contract',blockers[0]!);
  const effects:SellingEffect[]=[],warnings:string[]=[];
  const products=new Map(masters.products.map(item=>[item.record.sku,item.record]));
  const closed=new Set(runs.filter(run=>run.dataset===dataset).flatMap(run=>run.effects.flatMap(effect=>effect.type==='period.closed'?[effect.period]:[])));
  const admit=(date:string)=>{if(closed.has(date.slice(0,7)))refuse('occurredOn','An affected date falls in a closed month. Use a separately evidenced correction in an open month.');};
  admit(input.occurredOn);
  const event=(eventType:ReturnType<typeof saleEventSchema.parse>['eventType'],entityRef:string,occurredOn:string,amount:string|null,payload:z.input<typeof saleEventSchema>['payload'])=>{admit(occurredOn);effects.push({type:'selling.event',record:saleEventSchema.parse({eventId:digest({dataset,eventType,entityRef}),eventType,entityRef,occurredOn,currency:'USD',amount,payload,status:'UNPOSTED'})});};
  const timeline=runs.filter(run=>run.dataset===dataset).flatMap(run=>run.effects.flatMap(effect=>effect.type==='stock.moved'&&effect.move.condition==='sellable'?[{sku:effect.move.sku,date:run.occurredOn,delta:effect.move.qtyPieces}]:effect.type==='procurement.movement'?[{sku:effect.record.sku,date:effect.record.occurredOn,delta:effect.record.qtyPieces}]:effect.type==='selling.shipment'?effect.record.lines.map(line=>({sku:line.sku,date:effect.record.shipDate,delta:new Decimal(line.qtyPieces).negated().toFixed(0)})):[]));
  function dispatch(order:SellOrder,shipDate:string,trackingRef:string,evidenceRef:string){
    admit(shipDate);if(shipDate<order.orderDate)refuse('shipDate','The ship date cannot be before the order date.');
    if(projection.shipments.some(item=>item.orderId===order.orderId))refuse('orderId','This order is already dispatched. Its original shipment cannot be edited.');
    const lines=order.lines.map(line=>{const product=products.get(line.sku);if(!product||product.productType!=='sellable')refuse('orderId','A sellable product is missing from this dataset.');const qty=new Decimal(line.qtySaleUnits).times(product.piecesPerSaleUnit);const movement={sku:line.sku,date:shipDate,delta:qty.negated().toFixed(0)};const byDay=new Map<string,InstanceType<typeof Decimal>>();for(const item of [...timeline,movement].filter(item=>item.sku===line.sku))byDay.set(item.date,(byDay.get(item.date)??new Decimal(0)).plus(item.delta));let balance=new Decimal(0);for(const day of [...byDay.keys()].sort()){balance=balance.plus(byDay.get(day)!);if(balance.isNegative())refuse('orderId','There are not enough counted sellable pieces on the dispatch date. Opening preparation is not stock; stock booking is M3.');}timeline.push(movement);return {sku:line.sku,qtyPieces:qty.toFixed(0)};});
    effects.push({type:'selling.shipment',record:shipmentSchema.parse({orderId:order.orderId,shipDate,trackingRef,evidenceRef,lines})});
    event('order.shipped',order.orderId,shipDate,order.gross,{shipDate});
    event('order.cogs_relieved',order.orderId,shipDate,null,{cost_basis:'provisional'});
  }
  const deals=new Map(projection.deals.map(item=>[item.record.dealId,item]));
  function recordDeal(record:Deal,previousRunId:string|null){
    const prior=deals.get(record.dealId);if((prior?.runId??null)!==previousRunId)refuse('previousRunId','This deal changed or already exists. Reopen its latest record.');
    const paid=['paid','shipped','followed_up'];
    if(dataset==='ACTUAL'&&paid.includes(record.status))refuse('record.status','Paid ACTUAL Instagram deals need the missing wallet-statement and ledger evidence flow. No payment can be claimed yet.');
    const effectiveOn=record.shipDate??record.paidAt??record.quotedAt??record.enquiryAt;admit(effectiveOn);
    for(const line of record.lines)if(line.sku&&(!products.has(line.sku)||products.get(line.sku)!.productType!=='sellable'))refuse('record.lines','Choose sellable products already recorded in this dataset.');
    if(record.walletTxnId&&[...deals.values()].some(item=>item.record.dealId!==record.dealId&&item.record.walletTxnId===record.walletTxnId))refuse('record.walletTxnId','That wallet transaction already belongs to another deal.');
    if(prior){
      const old=prior.record;
      if(canonical(old)===canonical(record))return;
      if(old.status==='lost'||old.status==='followed_up'||record.status===old.status||(record.status!=='lost'&&igStatusSchema.options.indexOf(record.status)<igStatusSchema.options.indexOf(old.status)))refuse('record.status','A deal must move forward. A final state cannot be reopened or edited.');
      if(old.customerRef!==record.customerRef||old.enquiryAt!==record.enquiryAt)refuse('record','The customer reference and enquiry date cannot change.');
      if(record.lines.length<old.lines.length)refuse('record.lines','A forward move cannot omit existing deal lines.');
      if(paid.includes(record.status)&&old.quoteTwd!==null&&old.quoteTwd!==record.quoteTwd)refuse('record.quoteTwd','The accepted quote cannot change when moving to paid or later.');
      if(paid.includes(old.status)&&(old.quoteTwd!==record.quoteTwd||old.walletTxnId!==record.walletTxnId||canonical(old.lines)!==canonical(record.lines)||old.shippingTwd!==record.shippingTwd||old.shipCountry!==record.shipCountry||old.paidAt!==record.paidAt))refuse('record','Paid quantities, prices, quote, destination, shipping charge, payment date, and wallet reference are fixed. Corrections need the later reversal workflow.');
      if(old.shipDate&&old.shipDate!==record.shipDate)refuse('record.shipDate','The original dispatch date cannot be edited.');
      const oldEffective=old.shipDate??old.paidAt??old.quotedAt??old.enquiryAt;if(effectiveOn<oldEffective)refuse('record','A forward status date cannot precede the earlier status.');
    }
    effects.push({type:'selling.deal',record,previousRunId,effectiveOn});deals.set(record.dealId,{runId:prior?.runId??'00000000-0000-4000-8000-000000000000',record});
  }
  if(input.action==='verify-etsy'){
    if(input.orderHeaderHash!==headerHashes.orderHeaderHash||input.statementHeaderHash!==headerHashes.statementHeaderHash)refuse('contract','Review the current exact header fingerprints. A different contract cannot be verified here.');
    if(projection.verified)refuse('contract','The exact current Etsy headers are already verified for this dataset.');
    effects.push({type:'selling.verified',...headerHashes,evidenceRef:input.evidenceRef});
  }
  if(input.action==='deal')recordDeal(input.record,input.previousRunId);
  if(input.action==='ig-import'){
    const period=sourcePeriod(input.filename,'ig_deals',dataset);const records=parseDeals(input.csvText);
    for(const record of records){if(record.enquiryAt.slice(0,7)!==period)refuse('filename','Each enquiry month must match the deal file month.');recordDeal(record,deals.get(record.dealId)?.runId??null);}
    effects.push({type:'selling.import',area:'instagram',sourceHash:shaText(input.csvText),recordsCreated:effects.length,warnings:['Instagram is a pipeline record, not wallet evidence or an accounting posting. No notification is sent.']});
  }
  if(input.action==='dispatch'){
    const order=projection.orders.find(item=>item.record.orderId===input.orderId);if(!order||order.runId!==input.previousRunId)refuse('orderId','Reopen the current order before dispatching.');if(input.occurredOn!==input.shipDate)refuse('shipDate','Use the dispatch date as the action date.');dispatch(order.record,input.shipDate,input.trackingRef,input.evidenceRef);
  }
  if(input.action==='etsy'){
    const period=sourcePeriod(input.orderFilename,'orderitems',dataset);if(sourcePeriod(input.statementFilename,'statement',dataset)!==period)refuse('filename','The order and statement filename months must agree.');
    const orders=parseOrders(input);const known=new Map(projection.orders.map(item=>[item.record.orderId,item.record]));
    const transactionIds=new Map(projection.orders.flatMap(item=>item.record.lines.map(line=>[line.transactionId,item.record.orderId] as const)));
    for(const order of orders){admit(order.orderDate);if(order.orderDate.slice(0,7)>period)refuse('ordersCsv','An order date is later than the statement month.');for(const line of order.lines){if(!products.has(line.sku)||products.get(line.sku)!.productType!=='sellable')refuse('ordersCsv','Add every sellable product in this dataset before importing orders.');if(transactionIds.has(line.transactionId)&&transactionIds.get(line.transactionId)!==order.orderId)refuse('ordersCsv','A transaction identifier belongs to another recorded order.');transactionIds.set(line.transactionId,order.orderId);}
      const prior=known.get(order.orderId);if(prior&&canonical(prior)!==canonical(order))refuse('ordersCsv','A previously imported order changed. The original cannot be overwritten.');known.set(order.orderId,order);
      if(!prior){effects.push({type:'selling.order',record:order});event('order.placed',order.orderId,order.orderDate,order.discountFundedBy==='seller'?order.buyerPaid:order.gross,{discount:order.discount,discount_funded_by:order.discountFundedBy,tax_remitted_by_platform:order.platformTax,tax_treatment_hint:order.country==='TW'?'domestic':'export'});if(order.importedShipDate)dispatch(order,order.importedShipDate,'',input.orderFilename);}
    }
    const parsed=parseStatement(input,period),prior=projection.statements.find(item=>item.period===period);
    if(prior&&prior.multisetDigest!==parsed.multisetDigest)refuse('statementCsv','The recorded statement multiset changed. A changed row or duplicate count needs founder review, not replacement.');
    const sales=new Set<string>();
    for(const row of parsed.rows){admit(row.occurredOn);if(row.orderRef&&!known.has(row.orderRef))refuse('statementCsv','A statement row refers to an unknown order.');if(row.type==='Sale'){if(sales.has(row.orderRef))refuse('statementCsv','A Sale control repeats for an order.');sales.add(row.orderRef);if(!new Decimal(row.amount!).eq(known.get(row.orderRef)!.gross))refuse('statementCsv','A Sale control does not equal the order gross before discount.');}}
    const residual=parsed.rows.reduce((sum,row)=>sum.plus(row.net),new Decimal(0));const deposits=parsed.rows.filter(row=>row.type==='Deposit');
    if(deposits.length!==1||!residual.isZero())warnings.push('Settlement composition is unresolved; do not treat a payout as reconciled.');
    if(orders.some(order=>!new Decimal(order.shippingDiscount).isZero()))warnings.push('Shipping-discount gross evidence needs review.');
    for(const row of parsed.rows)if(row.orderRef&&row.type!=='Sale'&&!sales.has(row.orderRef))warnings.push('An order fee has no Sale control in this statement.');
    const periodEnd=new Date(`${period}-01T00:00:00Z`);periodEnd.setUTCMonth(periodEnd.getUTCMonth()+1);periodEnd.setUTCDate(0);const end=periodEnd.toISOString().slice(0,10);
    for(const order of known.values())if(order.orderDate<=end&&!sales.has(order.orderId)&&!projection.statements.some(statement=>statement.rows.some(row=>row.type==='Sale'&&row.orderRef===order.orderId))){const age=(periodEnd.getTime()-Date.parse(`${order.orderDate}T00:00:00Z`))/86400000;if(age>=60)refuse('statementCsv','An order has no Sale control after sixty days. Resolve the aged exception first.');if(age>=35)warnings.push('An order has no Sale control after thirty-five days (risk).');}
    if([...orders.map(order=>order.orderDate),...parsed.rows.map(row=>row.occurredOn)].some(day=>day.endsWith('-01')||new Date(Date.parse(`${day}T00:00:00Z`)+86400000).getUTCDate()===1))warnings.push('Period-boundary dates need a timezone review (Asia/Taipei).');
    if(!prior){const statement=statementSchema.parse({period,...parsed,residual:residual.toFixed(4),compositionResolved:deposits.length===1&&residual.isZero()});effects.push({type:'selling.statement',record:statement});const feeCodes={'Transaction Fee':'transaction_fee','Processing Fee':'payment_processing_fee','Offsite Ads Fee':'offsite_ads_fee','Regulatory Operating Fee':'regulatory_operating_fee'} as const;
      for(const row of parsed.rows){if(row.type in feeCodes)event('order.fees_assessed',row.key,row.occurredOn,new Decimal(row.fee!).abs().toFixed(4),{order_id:row.orderRef,fee_components:[{code:feeCodes[row.type as keyof typeof feeCodes],amount:new Decimal(row.fee!).abs().toFixed(4)}]});else if(row.type==='Listing Fee')event('cost.recorded',row.key,row.occurredOn,new Decimal(row.fee!).abs().toFixed(4),{category:'platform_listing_fee',settled_via:'etsy_rail',listing_id:row.listingRef});else if(row.type==='Deposit'){if(dataset==='ACTUAL')refuse('statementCsv','A USD-to-USD deposit is a synthetic source shape. ACTUAL settlements require the first real TWD deposit contract and evidence.');event('settlement.received',row.key,row.occurredOn,new Decimal(row.net).abs().toFixed(4),{composition_unresolved:!statement.compositionResolved,covers_order_ids:statement.compositionResolved?[...new Set(parsed.rows.map(item=>item.orderRef).filter(Boolean))].sort():[],value_date:null,bank_credit_ref:null,bank_account_ref_partial:null});}}
    }
    if(prior&&effects.length===0){const original=runs.find(run=>run.dataset===dataset&&run.effects.some(effect=>effect.type==='selling.statement'&&effect.record.period===period));if(original)return structuredClone({kind:original.kind,dataset:original.dataset,occurredOn:original.occurredOn,input:original.input,effects:original.effects,idempotencyKey:original.idempotencyKey});}
    effects.push({type:'selling.import',area:'etsy',sourceHash:digest({orders:input.ordersCsv,statement:input.statementCsv}),recordsCreated:effects.filter(effect=>effect.type==='selling.order'||effect.type==='selling.statement'||effect.type==='selling.shipment').length,warnings:[...new Set(warnings)]});
  }
  if(!effects.length)refuse('record','Nothing changed. The original remains on file.');
  const candidate:Candidate={kind:'selling.record',dataset,occurredOn:input.occurredOn,input:structuredClone(input),effects:structuredClone(effects),idempotencyKey:key};
  if(effects.some(effect=>effect.type==='selling.shipment'))projectInventory([...runs,runSchema.parse({...candidate,runId:'00000000-0000-4000-8000-000000000000',createdAt:'2000-01-01T00:00:00.000Z',schemaVersion:1,prevHash:'0'.repeat(64),hash:'0'.repeat(64)})],dataset);
  return candidate;
}
export function validateSellingCandidate(candidate:Candidate,runs:readonly Run[]):void {
  if(canonical(planSelling(candidate.input,runs))!==canonical(candidate))refuse('record','The selling effects do not match the validated request.');
}
export function sellingSummary(effects:readonly SellingEffect[]):string[] {
  return [
    `${effects.filter(effect=>effect.type==='selling.order').length} new order(s); deposits are not revenue at placement.`,
    `${effects.filter(effect=>effect.type==='selling.shipment').length} dispatch(es); counted pieces leave stock and separate revenue/COGS events are queued.`,
    `${effects.filter(effect=>effect.type==='selling.deal').length} deal version(s); earlier snapshots remain unchanged.`,
    `${effects.filter(effect=>effect.type==='selling.event').length} UNPOSTED accounting event(s). Journal review and posting remain M4.`,
    ...effects.flatMap(effect=>effect.type==='selling.shipment'?effect.record.lines.map(line=>`Stock −${line.qtyPieces} pcs of ${line.sku}, dated ${effect.record.shipDate}. No zero cost is assumed.`):[]),
    ...effects.flatMap(effect=>effect.type==='selling.deal'?[`${effect.record.dealId} → ${effect.record.status}. Next follow-up: ${effect.record.followUpOn??'not recorded'}. This is a pipeline snapshot, not cash evidence.`]:[]),
    'No notification is sent. Buyer contact columns are discarded, not saved.'
  ];
}
