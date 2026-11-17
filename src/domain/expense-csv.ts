import header from '../../seed/schemas/receipts_header_v1.json';
import { parseCsv } from './csv';
import { expenseSchema } from './schemas/accounting';
import { DomainError } from './errors';
import type { Dataset } from './schemas';
export function parseExpenses(csv:string,filename:string,dataset:Dataset){
 const match=/^(SAMPLE_)?receipts_(\d{4}-(?:0[1-9]|1[0-2]))\.csv$/.exec(filename);if(!match||Boolean(match[1])!==(dataset==='SAMPLE'))throw new DomainError('filename','Use a dated receipts file for this dataset.');
 const [observed,...rows]=parseCsv(csv),required=header.header,optional=header.optional_columns;if(!observed||required.some((key,i)=>observed[i]!==key)||observed.slice(required.length).some(key=>!optional.includes(key))||new Set(observed).size!==observed.length)throw new DomainError('csvText','Use the exact receipt header and supported optional columns.');
 if(!rows.length)throw new DomainError('csvText','Add at least one receipt.');
 const parsed=rows.map(row=>{if(row.length!==observed.length)throw new DomainError('csvText','Each receipt row must match its header.');const value=Object.fromEntries(observed.map((key,i)=>[key,row[i]??'']));if(!/^(?:0|[1-9]\d*)(?:\.\d{1,2})?$/.test(value.amount_twd??''))throw new DomainError('amountTwd','Receipt amounts use at most two decimal places.');
 const record=expenseSchema.parse({date:value.occurred_on,category:value.category,amountTwd:value.amount_twd,settledVia:value.settled_via,bankAccount:value.bank_account||'1121',channel:value.channel_attribution||'',description:value.description,evidenceRef:value.evidence_ref});if(!record.date.startsWith(match[2]!))throw new DomainError('date','Every receipt must belong to the filename month.');return record;});
 if(new Set(parsed.map(r=>r.evidenceRef)).size!==parsed.length)throw new DomainError('evidenceRef','A receipt evidence reference repeats in this file.');return parsed;
}
