import { z } from 'zod';
import poHeader from '../../seed/schemas/po_header_v1.json';
import grnHeader from '../../seed/schemas/grn_header_v1.json';
import invHeader from '../../seed/schemas/inv_header_v1.json';
import payHeader from '../../seed/schemas/pay_header_v1.json';
import countsHeader from '../../seed/schemas/counts_header_v2.json';
import { parseCsv } from './csv';
import { containsContactDetails } from './privacy';
import { DomainError } from './errors';
import { purchaseOrderSchema,receiptSchema,invoiceSchema,supplierPaymentSchema,stockCountSchema,type ProcurementPayload } from './schemas/procurement';

export const procurementHeaders={po:poHeader,grn:grnHeader,inv:invHeader,pay:payHeader,counts:countsHeader};
function fail(message:string):never {throw new DomainError('csvText',message);}
export function parseProcurementCsv(input:Extract<ProcurementPayload,{action:'import'}>,dataset:'SAMPLE'|'ACTUAL'){
  const schema=procurementHeaders[input.area];if(!schema.verified)fail('This CSV contract is unverified. Nothing can be imported.');
  const [header,...cells]=parseCsv(input.csvText);
  if(header?.some(key=>/carrier|duty/i.test(key)))fail('Carrier freight and duty need the later carrier-cost flow; they cannot be hidden in a supplier receipt.');
  if(!header||header.length!==schema.header.length||header.some((key,index)=>key!==schema.header[index]))fail('Use the exact current header and column order. Counts require v2 piece quantities.');
  if(!cells.length)fail('Add at least one document line.');
  const rows=cells.map(values=>{if(values.length!==header.length)fail('A document row has the wrong number of cells.');if(values.some(containsContactDetails))fail('Keep buyer contact details out of purchasing and stock files.');return Object.fromEntries(header.map((key,index)=>[key,values[index]!.trim()]));});
  const first=rows[0]!;
  const same=(fields:readonly string[])=>{if(rows.some(row=>fields.some(field=>row[field]!==first[field])))fail('Document-level fields conflict between lines.');};
  const lineNo=(row:Record<string,string>)=>{if(!/^[1-9]\d{0,2}$/.test(row.line_no??''))fail('Line numbers must be positive whole numbers.');return parseInt(row.line_no!,10);};
  const yesNo=(value:string|undefined)=>{if(value!=='yes'&&value!=='no')fail('Use yes or no for credited damage and short-close flags.');return value==='yes';};
  const prefix=dataset==='SAMPLE'?'SAMPLE_':'';
  const expected=input.area==='po'?`${prefix}po_${first.po_number}.csv`:input.area==='grn'?`${prefix}grn_${first.po_number}_${first.receipt_no}.csv`:input.area==='inv'?`${prefix}inv_${first.invoice_no}.csv`:input.area==='pay'?`${prefix}pay_${first.payment_ref}.csv`:`${prefix}count_${first.counted_at}.csv`;
  if(input.filename!==expected)fail('The prescribed filename must match the document identifier/date and current dataset.');
  if(input.area==='po'){
    same(['po_number','supplier_ref','po_date','target_delivery_date','currency','payment_terms','incoterm','quote_ref','status']);
    return {action:'po' as const,record:purchaseOrderSchema.parse({poNumber:first.po_number,supplierRef:first.supplier_ref,poDate:first.po_date,targetDeliveryDate:first.target_delivery_date,currency:first.currency,paymentTerms:first.payment_terms,incoterm:first.incoterm,quoteRef:first.quote_ref,status:first.status,lines:rows.map(row=>({lineNo:lineNo(row),sku:row.sku,qtyPieces:row.qty_pieces,unitPriceTwd:row.unit_price_twd,setupChargeTwd:row.setup_charge_twd,lineTotalTwd:row.line_total_twd,moqPieces:row.min_order_qty_pieces||null,artworkRef:row.artwork_ref,evidenceRef:row.evidence_ref})).sort((left,right)=>left.lineNo-right.lineNo)})};
  }
  if(input.area==='grn'){
    same(['po_number','receipt_no','received_on']);
    return {action:'receipt' as const,record:receiptSchema.parse({poNumber:first.po_number,receiptNo:first.receipt_no,receivedOn:first.received_on,lines:rows.map(row=>({lineNo:lineNo(row),sku:row.sku,qtyGood:row.qty_pieces_good,qtyDamaged:row.qty_pieces_damaged,damagedCredited:yesNo(row.damaged_credited),shortClose:yesNo(row.short_close),shortCloseReason:row.short_close_reason,evidenceRef:row.evidence_ref})).sort((left,right)=>left.lineNo-right.lineNo)})};
  }
  if(input.area==='inv'){
    same(['invoice_no','gui_no','invoice_date','po_number','receipt_no','freight_twd','tax_twd','tax_creditable_twd','invoice_total_twd','deposit_applied_twd','evidence_ref']);
    return {action:'invoice' as const,record:invoiceSchema.parse({invoiceNo:first.invoice_no,guiNo:first.gui_no,invoiceDate:first.invoice_date,poNumber:first.po_number,receiptNo:first.receipt_no,freightTwd:first.freight_twd,taxTwd:first.tax_twd,taxCreditableTwd:first.tax_creditable_twd,invoiceTotalTwd:first.invoice_total_twd,depositAppliedTwd:first.deposit_applied_twd,evidenceRef:first.evidence_ref,lines:rows.map(row=>({lineNo:lineNo(row),sku:row.sku,qtyInvoiced:row.qty_pieces_invoiced,unitPriceTwd:row.unit_price_twd,setupChargeTwd:row.setup_charge_twd,lineAmountTwd:row.line_amount_twd,statedTaxTwd:null})).sort((left,right)=>left.lineNo-right.lineNo)})};
  }
  if(input.area==='pay'){
    if(rows.length!==1)fail('A payment file must contain exactly one cash movement.');
    return {action:'payment' as const,record:supplierPaymentSchema.parse({paymentRef:first.payment_ref,paidOn:first.paid_on,supplierRef:first.supplier_ref,poNumber:first.po_number,invoiceNo:first.invoice_no,paymentKind:first.payment_kind,amountTwd:first.amount_twd,bankAccount:first.bank_account,bankRef:first.bank_ref,evidenceRef:first.evidence_ref})};
  }
  same(['counted_at','evidence_ref']);
  return {action:'count' as const,record:stockCountSchema.parse({countedAt:first.counted_at,evidenceRef:first.evidence_ref,lines:rows.map(row=>({sku:row.sku,qtyPieces:row.qty_pieces,agreedUnitCostTwd:row.agreed_unit_cost_twd,condition:row.condition}))}),founderConfirmed:input.founderConfirmed};
}
export type ParsedProcurementCsv=ReturnType<typeof parseProcurementCsv>;
export type PurchaseOrder=z.infer<typeof purchaseOrderSchema>;
