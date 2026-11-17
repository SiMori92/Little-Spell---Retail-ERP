import type { z } from 'zod';
import { canonical,digest } from './canonical';
import Decimal from './decimal';
import { DomainError } from './errors';
import { projectMasters } from './master-projection';
import { approvedAccounts } from './masters';
import { projectProcurement } from './procurement-projection';
import { projectInventory } from './inventory-projection';
import { parseProcurementCsv } from './procurement-csv';
import { exactMoney,proRataDeposit,valueReceipt } from './landed-cost';
import { postCount,postReceipt,postSupplierPayment } from './posting/procurement';
import { procurementPayloadSchema,receiptMatchSchema,type ProcurementEffect,stockCountSchema } from './schemas/procurement';
import { runSchema,type Candidate,type Run,type Effect,type Journal } from './schemas';

function refuse(field:string,message:string):never {throw new DomainError(field,message);}
const candidateFrom=(run:Run):Candidate=>structuredClone({kind:run.kind,dataset:run.dataset,occurredOn:run.occurredOn,input:run.input,effects:run.effects,idempotencyKey:run.idempotencyKey});
export function procurementId(key:string):string {const hash=digest(key);return `${hash.slice(0,8)}-${hash.slice(8,12)}-4${hash.slice(13,16)}-8${hash.slice(17,20)}-${hash.slice(20,32)}`;}
export function planProcurement(raw:unknown,runs:readonly Run[]):Candidate {
  const input=procurementPayloadSchema.parse(raw),base=projectProcurement(runs),dataset=base.dataset,masters=projectMasters(runs,dataset);
  if(input.action==='count')input.record.lines.sort((left,right)=>left.sku.localeCompare(right.sku)||left.condition.localeCompare(right.condition));
  const key=input.action==='import'?`procurement-import:${dataset}:${input.area}:${digest(input.csvText)}`:`procurement-record:${input.idempotencyKey}`;
  const existing=runs.find(run=>run.idempotencyKey===key);
  if(existing){if(input.action!=='import'&&canonical(existing.input)!==canonical(input))refuse('idempotencyKey','This request key already belongs to a different action. Reload the form.');return candidateFrom(existing);}
  if(input.expectedHeadHash&&input.expectedHeadHash!==(runs.at(-1)?.hash??'0'.repeat(64)))refuse('expectedHeadHash','Records changed after preview. Preview again before confirming.');
  const command=input.action==='import'?parseProcurementCsv(input,dataset):input;
  const effects:Effect[]=[],closed=new Set(runs.filter(run=>run.dataset===dataset).flatMap(run=>run.effects.flatMap(effect=>effect.type==='period.closed'?[effect.period]:[])));
  const admit=(date:string)=>{if(closed.has(date.slice(0,7)))refuse('occurredOn','An effective document or journal date falls inside a closed month. Use an evidenced correction in an open month.');};
  admit(input.occurredOn);
  if(!masters.accounts.some(item=>item.record.code==='1266'))effects.push({type:'procurement.account',record:approvedAccounts.find(item=>item.code==='1266')!,sourceRef:'app/acct/migrations/0008_supplier_prepayments_account.py'});
  const fakeRun=()=>runSchema.parse({runId:procurementId(`projection:${key}`),kind:'procurement.record',dataset,occurredOn:input.occurredOn,createdAt:'2000-01-01T00:00:00.000Z',schemaVersion:1,input,effects,idempotencyKey:key,prevHash:'0'.repeat(64),hash:'0'.repeat(64)});
  const history=()=>effects.length?[...runs,fakeRun()]:[...runs];
  const snapshot=()=>projectProcurement(history(),dataset);
  const post=(entry:Journal)=>{admit(entry.occurredOn);effects.push({type:'journal.posted',entry,opening:null,founderAuthorization:null});};
  const status=(poNumber:string,value:z.infer<typeof import('./schemas/procurement').poStatusSchema>,date:string)=>{admit(date);effects.push({type:'procurement.status',poNumber,status:value,effectiveOn:date});};
  const movement=(sku:string,qty:string,value:string,date:string,kind:'opening'|'received'|'adjusted',sourceRef:string)=>{admit(date);effects.push({type:'procurement.movement',record:{moveId:procurementId(`${dataset}:${kind}:${sourceRef}:${sku}`),occurredOn:date,sku,kind,qtyPieces:qty,valueTwd:exactMoney(value),sourceRef}});};
  function identical(type:ProcurementEffect['type'],record:unknown):Run|undefined {return [...runs].reverse().find(run=>run.dataset===dataset&&run.effects.some(effect=>effect.type===type&&'record'in effect&&canonical(effect.record)===canonical(record)));}
  const order=(poNumber:string)=>{const found=snapshot().orders.find(item=>item.record.poNumber===poNumber);if(!found)refuse('record.poNumber','Record this purchase order in the current dataset first.');return found;};
  const inTransit=(poNumber:string)=>runs.some(run=>run.dataset===dataset&&run.effects.some(effect=>effect.type==='journal.posted'&&effect.entry.sourceEvent==='po.in_transit')&&(typeof run.input!=='object'||run.input===null||!('poNumber'in run.input)||run.input.poNumber===poNumber));
  function matchPair(poNumber:string,receiptNo:string){
    const state=snapshot(),po=state.orders.find(item=>item.record.poNumber===poNumber)!,receipt=state.receipts.find(item=>item.record.poNumber===poNumber&&item.record.receiptNo===receiptNo),invoice=state.invoices.find(item=>item.record.poNumber===poNumber&&item.record.receiptNo===receiptNo);
    if(!receipt||!invoice||state.matches.some(item=>item.poNumber===poNumber&&item.receiptNo===receiptNo))return;
    if(!['sent','acknowledged'].includes(po.status))return;
    if(inTransit(poNumber))return;
    if(new Decimal(invoice.record.taxCreditableTwd).gt(0)&&(!masters.business||masters.business.record.taxRegime==='unregistered'))return;
    if(state.payments.some(item=>item.poNumber===poNumber&&item.paymentKind==='deposit'&&item.paidOn>receipt.record.receivedOn))return;
    const received=[...receipt.record.lines].sort((left,right)=>left.lineNo-right.lineNo),billed=[...invoice.record.lines].sort((left,right)=>left.lineNo-right.lineNo);
    if(received.length!==billed.length||received.some((line,index)=>line.lineNo!==billed[index]!.lineNo||!new Decimal(line.qtyGood).plus(line.damagedCredited?'0':line.qtyDamaged).eq(billed[index]!.qtyInvoiced)))return;
    const values=valueReceipt(received.map((line,index)=>({lineNo:line.lineNo,sku:line.sku,inventoryAccount:masters.products.find(item=>item.record.sku===line.sku)!.record.productType==='packaging'?'1233':'1231',qtyGood:line.qtyGood,qtyDamaged:line.damagedCredited?'0':line.qtyDamaged,lineAmount:billed[index]!.lineAmountTwd,setup:billed[index]!.setupChargeTwd,statedTax:billed[index]!.statedTaxTwd})),invoice.record.freightTwd,invoice.record.taxTwd,invoice.record.taxCreditableTwd);
    const deposits=state.payments.filter(item=>item.poNumber===poNumber&&item.paymentKind==='deposit').reduce((sum,item)=>sum.plus(item.amountTwd),new Decimal(0));
    const applied=state.matches.filter(item=>item.poNumber===poNumber).reduce((sum,item)=>sum.plus(item.depositAppliedTwd),new Decimal(0));
    const covered=new Set(state.receipts.filter(item=>item.record.poNumber===poNumber&&(item.record.receiptNo===receiptNo||state.matches.some(match=>match.poNumber===poNumber&&match.receiptNo===item.record.receiptNo))).flatMap(item=>item.record.lines.map(line=>line.lineNo)));
    const completes=po.record.lines.every(line=>covered.has(line.lineNo));
    const depositApplied=proRataDeposit(exactMoney(deposits),exactMoney(invoice.record.lines.reduce((sum,line)=>sum.plus(line.lineAmountTwd),new Decimal(0))),po.poValueTwd,exactMoney(applied),completes);
    if(new Decimal(depositApplied).gt(invoice.record.invoiceTotalTwd))return;
    const match=receiptMatchSchema.parse({poNumber,receiptNo,invoiceNo:invoice.record.invoiceNo,receivedOn:receipt.record.receivedOn,depositAppliedTwd:depositApplied,invoiceStatedDepositTwd:invoice.record.depositAppliedTwd,invoiceTotalTwd:invoice.record.invoiceTotalTwd,taxCreditableTwd:invoice.record.taxCreditableTwd,lines:values,journalId:procurementId(`${dataset}:receipt:${poNumber}:${receiptNo}`)});
    effects.push({type:'procurement.matched',record:match});post(postReceipt(match));
    for(const line of values)if(line.inventoryAccount==='1231'&&new Decimal(line.qtyGood).gt(0))movement(line.sku,line.qtyGood,line.goodValue,receipt.record.receivedOn,'received',`${poNumber}/${receiptNo}/${line.lineNo}`);
    if(completes){const short=state.receipts.filter(item=>item.record.poNumber===poNumber).some(item=>item.record.lines.some(line=>line.shortClose));status(poNumber,short?'short_closed':'received',receipt.record.receivedOn);}
  }
  function closeIfSettled(poNumber:string,date:string){const state=snapshot(),po=state.orders.find(item=>item.record.poNumber===poNumber)!;const invoices=state.invoices.filter(item=>item.record.poNumber===poNumber);if(['received','short_closed'].includes(po.status)&&new Decimal(po.openDepositTwd).isZero()&&invoices.length&&invoices.every(item=>item.matched&&new Decimal(item.openAmountTwd).isZero()))status(poNumber,'closed',date);}
  let duplicate:Run|undefined;
  if(command.action==='po'){
    const record=command.record;admit(record.poDate);const prior=base.orders.find(item=>item.record.poNumber===record.poNumber);
    if(prior&&canonical(prior.record)===canonical(record))duplicate=identical('procurement.po',record);
    else{
      if(input.action==='po'&&(prior?.runId??null)!==input.previousRunId)refuse('previousRunId','This purchase order changed or already exists. Reopen the latest version.');
      const supplier=masters.suppliers.find(item=>item.record.supplierRef===record.supplierRef);if(!supplier||supplier.record.currency!=='TWD')refuse('record.supplierRef','Purchasing needs a supplier in this dataset whose currency is TWD.');
      for(const line of record.lines){const product=masters.products.find(item=>item.record.sku===line.sku)?.record;if(!product)refuse('record.lines','Add every product in the current dataset before ordering.');if(['sent','acknowledged'].includes(record.status)){const linked=masters.suppliers.find(item=>item.record.supplierRef===product.supplierRef)?.record;if(!linked||product.productType==='sellable'&&(!product.ingredientRef.startsWith('compliance/suppliers/')||!linked.declarationRef.startsWith('compliance/suppliers/')))refuse('record.lines','Sending requires supplier-linked products with ingredient and supplier declaration evidence. Packaging needs a linked supplier.');}}
      if(prior){if(['received','short_closed','closed','cancelled'].includes(prior.status))refuse('record','This purchase order is final and cannot change.');const forward={draft:['sent','cancelled'],sent:['acknowledged','cancelled'],acknowledged:['cancelled']} as const;if(record.status!==prior.status&&!(forward[prior.status as keyof typeof forward] as readonly string[]).includes(record.status))refuse('record.status','The purchase order must move forward through its lifecycle.');if(record.status==='cancelled'&&base.receipts.some(item=>item.record.poNumber===record.poNumber))refuse('record.status','A purchase order with received goods cannot be cancelled.');if(record.lines.length<prior.record.lines.length)refuse('record.lines','Omitting a line is not a deletion. Keep every existing line.');if(prior.status!=='draft'){if(record.supplierRef!==prior.record.supplierRef||record.currency!==prior.record.currency||record.quoteRef!==prior.record.quoteRef||record.lines.length!==prior.record.lines.length||record.lines.some((line,index)=>['sku','qtyPieces','unitPriceTwd','setupChargeTwd'].some(field=>line[field as keyof typeof line]!==prior.record.lines[index]![field as keyof typeof line])))refuse('record','Sent commitments freeze the supplier, quote, line set, quantities, and prices.');}}
      effects.push({type:'procurement.po',record,previousRunId:prior?.runId??null});if(!prior){status(record.poNumber,'draft',record.poDate);if(['sent','acknowledged'].includes(record.status))status(record.poNumber,'sent',record.poDate);if(record.status==='acknowledged')status(record.poNumber,'acknowledged',record.poDate);if(record.status==='cancelled')status(record.poNumber,'cancelled',record.poDate);}else if(prior.status!==record.status)status(record.poNumber,record.status,input.occurredOn);
    }
  }
  if(command.action==='receipt'){
    const record=command.record;admit(record.receivedOn);const prior=base.receipts.find(item=>item.record.poNumber===record.poNumber&&item.record.receiptNo===record.receiptNo);
    if(prior){if(canonical(prior.record)!==canonical(record))refuse('record','A booked goods receipt cannot be replaced.');duplicate=identical('procurement.receipt',record);}else{
      const po=order(record.poNumber);if(!['sent','acknowledged'].includes(po.status))refuse('record.poNumber','Receive only a sent or acknowledged purchase order.');if(inTransit(record.poNumber))refuse('record.poNumber','A receipt after goods-in-transit needs the later dedicated matching flow. It cannot be absorbed here.');if(record.receivedOn<po.record.poDate)refuse('record.receivedOn','The receipt date cannot be before the order date.');
      for(const line of record.lines){const poLine=po.record.lines.find(item=>item.lineNo===line.lineNo);if(!poLine||poLine.sku!==line.sku)refuse('record.lines','Receipt lines must identify the matching purchase-order lines and products.');if(base.receipts.some(item=>item.record.poNumber===record.poNumber&&item.record.lines.some(existing=>existing.lineNo===line.lineNo)))refuse('record.lines','A PO line may have one delivery only. Split deliveries for a single line are not supported.');const accepted=new Decimal(line.qtyGood).plus(line.damagedCredited?'0':line.qtyDamaged);if(accepted.lt(poLine.qtyPieces)!==line.shortClose)refuse('record.lines','A short delivery needs short-close and its reason; full deliveries must not short-close.');}
      effects.push({type:'procurement.receipt',record});matchPair(record.poNumber,record.receiptNo);closeIfSettled(record.poNumber,record.receivedOn);
    }
  }
  if(command.action==='invoice'){
    const record=command.record;admit(record.invoiceDate);const prior=base.invoices.find(item=>item.record.invoiceNo===record.invoiceNo);
    if(prior){if(canonical(prior.record)!==canonical(record))refuse('record','A booked supplier invoice cannot be replaced.');duplicate=identical('procurement.invoice',record);}else{
      const po=order(record.poNumber);if(!['sent','acknowledged'].includes(po.status))refuse('record.poNumber','Supplier invoices need a sent or acknowledged purchase order.');if(new Decimal(record.taxCreditableTwd).gt(0)&&(!masters.business||masters.business.record.taxRegime==='unregistered'))refuse('record.taxCreditableTwd','Creditable tax needs an explicitly recorded assessed/general tax regime as well as a GUI.');if(base.invoices.some(item=>item.record.poNumber===record.poNumber&&item.record.receiptNo===record.receiptNo))refuse('record.receiptNo','This receipt already has an immutable supplier invoice.');
      for(const line of record.lines){const poLine=po.record.lines.find(item=>item.lineNo===line.lineNo);if(!poLine||poLine.sku!==line.sku||poLine.unitPriceTwd!==line.unitPriceTwd||poLine.setupChargeTwd!==line.setupChargeTwd)refuse('record.lines','Invoice products, per-piece prices, and setup must match the accepted purchase order; variances are not absorbed.');if(base.invoices.some(item=>item.record.poNumber===record.poNumber&&item.record.lines.some(existing=>existing.lineNo===line.lineNo)))refuse('record.lines','A PO line may be invoiced once only.');}
      effects.push({type:'procurement.invoice',record});matchPair(record.poNumber,record.receiptNo);closeIfSettled(record.poNumber,record.invoiceDate);
    }
  }
  if(command.action==='payment'){
    const record=command.record;admit(record.paidOn);const prior=base.payments.find(item=>item.paymentRef===record.paymentRef);
    if(prior){if(canonical(prior)!==canonical(record))refuse('record','A supplier payment reference is immutable and cannot be reused.');duplicate=identical('procurement.payment',record);}else{
      const po=order(record.poNumber);if(record.supplierRef!==po.record.supplierRef)refuse('record.supplierRef','The payment supplier must match the purchase order.');if(record.paidOn<po.record.poDate)refuse('record.paidOn','The payment date cannot be before the purchase order.');
      if(record.paymentKind==='deposit'){if(!['sent','acknowledged'].includes(po.status)||base.receipts.some(item=>item.record.poNumber===record.poNumber))refuse('record.paymentKind','A deposit needs a sent/acknowledged PO before any goods receipt exists.');const priorDeposits=base.payments.filter(item=>item.poNumber===record.poNumber&&item.paymentKind==='deposit').reduce((sum,item)=>sum.plus(item.amountTwd),new Decimal(0));if(priorDeposits.plus(record.amountTwd).gt(po.poValueTwd))refuse('record.amountTwd','Cumulative deposits cannot exceed the PO value excluding tax.');}
      else if(record.paymentKind==='balance'){const invoice=base.invoices.find(item=>item.record.invoiceNo===record.invoiceNo&&item.record.poNumber===record.poNumber),match=base.matches.find(item=>item.invoiceNo===record.invoiceNo);if(!invoice||!invoice.matched||!match)refuse('record.invoiceNo','A balance payment requires a matched and posted supplier invoice.');if(record.paidOn<invoice.record.invoiceDate||record.paidOn<match.receivedOn)refuse('record.paidOn','A balance payment cannot precede its invoice or receipt.');if(new Decimal(record.amountTwd).gt(invoice.openAmountTwd))refuse('record.amountTwd','This would overpay the invoice. Supplier payables must not become a debit.');}
      else{if(po.status!=='cancelled')refuse('record.paymentKind','A deposit refund or forfeiture requires a cancelled purchase order.');if(new Decimal(record.amountTwd).gt(po.openDepositTwd))refuse('record.amountTwd','The refund/forfeiture cannot exceed the remaining deposit.');}
      effects.push({type:'procurement.payment',record});post(postSupplierPayment(record,procurementId(`${dataset}:payment:${record.paymentRef}`)));closeIfSettled(record.poNumber,record.paidOn);
    }
  }
  if(command.action==='count'){
    if(!command.founderConfirmed)refuse('founderConfirmed','Confirm this is your own evidenced physical stock count.');
    const record=stockCountSchema.parse({...command.record,lines:[...command.record.lines].sort((left,right)=>left.sku.localeCompare(right.sku)||left.condition.localeCompare(right.condition))});admit(record.countedAt);
    const prior=base.counts.find(item=>item.record.evidenceRef===record.evidenceRef);if(prior){if(canonical(prior.record)!==canonical(record))refuse('record.evidenceRef','This count evidence is already booked and cannot change.');duplicate=identical('procurement.count',record);}else{
      const allSkus=new Set(masters.products.map(item=>item.record.sku)),sellable=new Set(record.lines.filter(line=>line.condition==='sellable').map(line=>line.sku));
      if(!allSkus.size||[...allSkus].some(sku=>!sellable.has(sku))||record.lines.some(line=>!allSkus.has(line.sku)))refuse('record.lines','Count every active product explicitly, including zero rows. Unknown or omitted products cannot pass.');
      for(const line of record.lines){if(line.condition==='damaged_unsellable'&&!sellable.has(line.sku))refuse('record.lines','A damaged memo needs a sellable count line for the same product.');if(masters.products.find(item=>item.record.sku===line.sku)!.record.productType==='packaging'&&(!new Decimal(line.qtyPieces).isZero()||!new Decimal(line.agreedUnitCostTwd).isZero()))refuse('record.lines','Packaging counts must be explicit zero in this reference scope; supplier packaging receipts are valued separately, outside sellable WAC.');}
      const inventory=projectInventory(runs,dataset,record.countedAt),opening=!inventory.openingRecorded;
      if(opening&&runs.some(run=>run.dataset===dataset&&run.effects.some(effect=>effect.type==='stock.moved'||effect.type==='procurement.movement'||effect.type==='selling.shipment')))refuse('record','An opening count must precede stock activity. Existing stock histories need a reconciled opening, not an additive count.');
      const rows:{value:string;account:string}[]=[];effects.push({type:'procurement.count',record,kind:opening?'opening':'adjustment'});
      for(const line of record.lines.filter(item=>item.condition==='sellable')){
        const product=masters.products.find(item=>item.record.sku===line.sku)!.record;if(product.productType==='packaging')continue;
        if(opening){const value=exactMoney(new Decimal(line.qtyPieces).times(line.agreedUnitCostTwd));movement(line.sku,line.qtyPieces,value,record.countedAt,'opening',record.evidenceRef);rows.push({value,account:'1231'});}
        else{const position=inventory.positions.find(item=>item.sku===line.sku)!;const delta=new Decimal(position.qtyPieces).minus(line.qtyPieces);if(delta.isNegative())refuse('record.lines','A stock count cannot add unexplained pieces. Use an evidenced goods receipt for increases.');if(delta.isZero())continue;const value=delta.eq(position.qtyPieces)?position.valueTwd:exactMoney(new Decimal(position.valueTwd).times(delta).div(position.qtyPieces));if(new Decimal(value).lte(0))refuse('record.lines','A decrease needs a tied, positive weighted-average cost; it cannot be guessed or rounded to zero.');movement(line.sku,delta.negated().toFixed(0),new Decimal(value).negated().toFixed(4),record.countedAt,'adjusted',record.evidenceRef);rows.push({value,account:'1231'});}
      }
      if(rows.length)post(postCount(procurementId(`${dataset}:count:${record.evidenceRef}`),record.countedAt,rows,opening));
    }
  }
  if(duplicate)return candidateFrom(duplicate);
  if(input.action==='import')effects.push({type:'procurement.import',area:input.area,sourceHash:digest(input.csvText)});
  if(!effects.length)refuse('record','Nothing changed. The original remains on file.');
  const latestAdjustment=base.counts.filter(item=>item.kind==='adjustment').map(item=>item.record.countedAt).sort().at(-1);
  if(latestAdjustment&&effects.some(effect=>effect.type==='procurement.movement'&&effect.record.occurredOn<latestAdjustment))refuse('occurredOn','Backdated stock would change an already booked count valuation. Use a separately evidenced correction instead.');
  projectInventory(history(),dataset);
  return {kind:'procurement.record',dataset,occurredOn:input.occurredOn,input:structuredClone(input),effects:structuredClone(effects),idempotencyKey:key};
}
export function validateProcurementCandidate(candidate:Candidate,runs:readonly Run[]):void {if(canonical(planProcurement(candidate.input,runs))!==canonical(candidate))refuse('record','The procurement effects do not match the validated request.');}
export function procurementSummary(effects:readonly Effect[]):string[]{return effects.flatMap(effect=>effect.type==='procurement.account'?['The reference-approved supplier-deposit account is appended to the chart; existing history is unchanged.']:effect.type==='procurement.po'?[`Purchase order ${effect.record.poNumber}: ${effect.record.status}. A commitment alone posts no money.`]:effect.type==='procurement.receipt'?[`Receipt ${effect.record.receiptNo} recorded. Only an agreeing supplier invoice can create stock and payable.`]:effect.type==='procurement.invoice'?[`Invoice ${effect.record.invoiceNo}: supplier total NT$${effect.record.invoiceTotalTwd}. Unmatched documents remain visible and unposted.`]:effect.type==='procurement.matched'?[`Three-way match: you owe NT$${exactMoney(new Decimal(effect.record.invoiceTotalTwd).minus(effect.record.depositAppliedTwd))} after applying NT$${effect.record.depositAppliedTwd} of deposit.`]:effect.type==='procurement.payment'?[`${effect.record.paymentKind}: NT$${effect.record.amountTwd}, with the original payment kept immutable.`]:effect.type==='procurement.movement'?[`Stock ${effect.record.qtyPieces} pcs of ${effect.record.sku}; exact value change NT$${effect.record.valueTwd}.`]:effect.type==='procurement.count'?[`Your ${effect.kind} physical count is recorded; damaged pieces are zero-value memos, never sellable stock.`]:effect.type==='journal.posted'?[`A balanced ${effect.entry.sourceEvent} journal is booked on ${effect.entry.occurredOn}.`]:[]);}
