import 'server-only';
import { mkdir,mkdtemp,readFile,writeFile } from 'node:fs/promises';
import { basename,join,resolve } from 'node:path';
import { RunStore } from '../src/server/store';
import { planMasters } from '../src/domain/masters';
import { planProcurement } from '../src/domain/procurement';
import { planAccounting } from '../src/domain/accounting';
import { projectMasters } from '../src/domain/master-projection';
import { buildReports } from '../src/domain/reporting';
import Decimal from '../src/domain/decimal';
import { canonical } from '../src/domain/canonical';
await mkdir(resolve('.tools/parity'),{recursive:true});
const directory=await mkdtemp(join(resolve('.tools/parity'),'g3-')),store=new RunStore(directory);await store.initialize();
let ordinal=0;const fields=()=>({occurredOn:'2026-11-17',idempotencyKey:`parity-${++ordinal}`,expectedHeadHash:null});
for(const area of ['suppliers','products'] as const){const filename=`SAMPLE_${area}_2026-09-27.csv`;await store.execute(async r=>planMasters({action:'import',...fields(),area,filename,csvText:await readFile(`seed/samples/g3/${filename}`,'utf8')},r));}
const masters=projectMasters(await store.read());await store.execute(async r=>planProcurement({action:'count',...fields(),founderConfirmed:true,record:{countedAt:'2026-01-01',evidenceRef:'synthetic-parity-opening',lines:masters.products.map(p=>({sku:p.record.sku,qtyPieces:'0',agreedUnitCostTwd:'0.0000',condition:'sellable'}))}},r));
const imports=[['po','SAMPLE_po_PO-2026-002.csv'],['pay','SAMPLE_pay_DEP-002.csv'],['grn','SAMPLE_grn_PO-2026-002_R1.csv'],['inv','SAMPLE_inv_INV-A.csv'],['pay','SAMPLE_pay_BAL-A.csv'],['grn','SAMPLE_grn_PO-2026-002_R2.csv'],['inv','SAMPLE_inv_INV-B.csv'],['pay','SAMPLE_pay_BAL-B.csv']] as const;
for(const [area,filename]of imports)await store.execute(async r=>planProcurement({action:'import',...fields(),area,filename,csvText:await readFile(`seed/samples/g3/${filename}`,'utf8'),founderConfirmed:true},r));
await store.execute(r=>planAccounting({action:'inventory-evidence',...fields(),evidenceRef:'synthetic-parity-journal-attribution'},r));
for(const [key,record]of [
 ['funding',{eventType:'owner.funds_moved',amount:'200000.0000',fundsType:'capital'}],
 ['accrual',{eventType:'period.accrued',amount:'1234.5678',expenseAccount:'6161',accrualAccount:'2193',basisNote:'Synthetic prorated license'}],
 ['tax-assessment',{eventType:'tax.assessed',amount:'1250.0000',needsProfessionalConfirmation:true}],
 ['tax-payment',{eventType:'tax.paid',amount:'1000.0000'}]
] as const){const saved=await store.execute(r=>planAccounting({action:'manual',...fields(),occurredOn:'2026-10-02',evidenceRef:`synthetic-parity-${key}`,record},r));const fact=saved.run.effects.find(e=>e.type==='accounting.fact');if(fact?.type!=='accounting.fact')throw Error('Missing parity fact.');await store.execute(r=>planAccounting({action:'post',...fields(),occurredOn:'2026-10-02',eventId:fact.record.id},r));}
const runs=await store.read(),reports=buildReports(runs,'2026-10');
const amount=(value:unknown)=>typeof value==='object'&&value!==null&&'amount' in value?value.amount:null;
const trialBalance=Object.fromEntries(reports.find(r=>r.slug==='trial-balance')!.rows.map(r=>[r.account,{debit:amount(r.debit),credit:amount(r.credit)}]));
const values=(slug:string)=>Object.fromEntries(reports.find(r=>r.slug===slug)!.rows.map(r=>[r.account,amount(r.balance)]));
const inventory=Object.fromEntries(reports.find(r=>r.slug==='inventory')!.rows.map(r=>[r.sku,{pieces:amount(r.pieces),value:amount(r.opsValue)}]));
const output={scenario:'G3 lifecycle, complete zero opening and explicit synthetic manual vouchers',trialBalance,profitLoss:values('profit-loss'),balanceSheet:values('balance-sheet'),inventory};
await writeFile('docs/PARITY_V2_G3.json',JSON.stringify(output,null,2)+'\n');
const reference:unknown=JSON.parse(await readFile('docs/PARITY_REFERENCE_G3.json','utf8'));
const diffs:{path:string;reference:unknown;v2:unknown}[]=[];
function compare(a:unknown,b:unknown,path='root'){if(typeof a==='object'&&a!==null&&typeof b==='object'&&b!==null){const x=a as Record<string,unknown>,y=b as Record<string,unknown>;for(const key of new Set([...Object.keys(x),...Object.keys(y)]))compare(x[key],y[key],`${path}.${key}`);}else if(typeof a==='string'&&typeof b==='string'&&/^-?\d+(\.\d+)?$/.test(a)&&/^-?\d+(\.\d+)?$/.test(b)){if(!new Decimal(a).eq(b))diffs.push({path,reference:a,v2:b});}else if(canonical(a??null)!==canonical(b??null))diffs.push({path,reference:a??null,v2:b??null});}
compare(reference,output);const countBefore=(await store.read()).length;
for(const [area,filename]of imports)await store.execute(async r=>planProcurement({action:'import',...fields(),area,filename:basename(filename),csvText:await readFile(`seed/samples/g3/${filename}`,'utf8'),founderConfirmed:true},r));
const result={scenario:output.scenario,differences:diffs,secondImportNewRuns:(await store.read()).length-countBefore};await writeFile('docs/PARITY_DIFF_G3.json',JSON.stringify(result,null,2)+'\n');console.log(JSON.stringify(result));if(diffs.length||result.secondImportNewRuns)process.exitCode=1;
