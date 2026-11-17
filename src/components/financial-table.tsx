'use client';
import { useState } from 'react';
import { CheckCircle2,CircleAlert } from 'lucide-react';
import * as Dialog from '@radix-ui/react-dialog';
import { RecordTable } from './record-table';
import { serializeCsv } from '@/domain/csv';
import type { ColumnDef } from '@tanstack/react-table';
export function FinancialTable({rows,label}:{rows:Record<string,string>[];label:string}){
 const [selected,setSelected]=useState<Record<string,string>|null>(null),keys=[...new Set(rows.flatMap(r=>Object.keys(r)))];
 const columns:ColumnDef<Record<string,string>>[]=keys.map(key=>({accessorKey:key,header:key,cell:({getValue})=>key==='status'?<span className={`badge ${['POSTED','CLOSED'].includes(String(getValue()))?'':'sample'}`}>{['POSTED','CLOSED'].includes(String(getValue()))?<CheckCircle2 size={12}/>:<CircleAlert size={12}/>} {String(getValue())}</span>:String(getValue()??'')}));
 function download(view:Record<string,string>[]){const url=URL.createObjectURL(new Blob([serializeCsv([keys,...view.map(r=>keys.map(k=>r[k]??''))])],{type:'text/csv'}));const a=document.createElement('a');a.href=url;a.download=`${label}.csv`;a.click();URL.revokeObjectURL(url);}
 return <><RecordTable data={rows} columns={columns} label={label} onExport={download} onSelect={setSelected} filterColumn={keys.includes('status')?'status':keys[0]} filterValues={[...new Set(rows.map(r=>r[keys.includes('status')?'status':keys[0]??'']??''))]}/><Dialog.Root open={!!selected} onOpenChange={open=>{if(!open)setSelected(null);}}><Dialog.Portal><Dialog.Overlay className="drawer-overlay"/><Dialog.Content className="card" style={{position:'fixed',right:0,top:0,height:'100dvh',width:'min(600px,95vw)',overflowY:'auto',zIndex:40}}><Dialog.Title>{label} record</Dialog.Title><Dialog.Description>Read the recorded values and evidence.</Dialog.Description>{selected&&Object.entries(selected).map(([k,v])=><p style={{overflowWrap:'anywhere'}} key={k}><strong>{k}</strong> {v}</p>)}<Dialog.Close className="button secondary">Close financial record</Dialog.Close></Dialog.Content></Dialog.Portal></Dialog.Root></>;
}
