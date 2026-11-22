'use client';
import { useState } from 'react';
import { flexRender, getCoreRowModel, getFilteredRowModel, getSortedRowModel, useReactTable, type ColumnDef, type ColumnFiltersState, type SortingState } from '@tanstack/react-table';
import { Button } from './ui/button';

export function RecordTable<Row>({data,columns,label,onSelect,onExport,filterColumn,filterValues=[]}: {data:Row[];columns:ColumnDef<Row>[];label:string;onSelect?:(row:Row)=>void;onExport:(rows:Row[])=>void;filterColumn?:string;filterValues?:string[]}) {
  const [search,setSearch] = useState(''), [sorting,setSorting] = useState<SortingState>([]), [columnFilters,setColumnFilters] = useState<ColumnFiltersState>([]);
  const table = useReactTable({data,columns,state:{globalFilter:search,sorting,columnFilters},onGlobalFilterChange:setSearch,onSortingChange:setSorting,onColumnFiltersChange:setColumnFilters,getCoreRowModel:getCoreRowModel(),getFilteredRowModel:getFilteredRowModel(),getSortedRowModel:getSortedRowModel()});
  return <>
    <div className="table-toolbar">
      <input aria-label={`Search ${label}`} placeholder={`Search ${label}…`} value={search} onChange={event=>setSearch(event.target.value)} />
      {filterColumn && <select aria-label={`Filter ${label}`} value={String(table.getColumn(filterColumn)?.getFilterValue() ?? '')} onChange={event=>table.getColumn(filterColumn)?.setFilterValue(event.target.value)}><option value="">All statuses / fields</option>{filterValues.map(value=><option value={value} key={value}>{value}</option>)}</select>}
      <Button variant="secondary" onClick={()=>onExport(table.getRowModel().rows.map(row=>row.original))}>Export current view</Button>
    </div>
    <div className="table-wrap" role="region" aria-label={`${label} table scroll area`} tabIndex={0}>
      <table aria-label={label}><thead>{table.getHeaderGroups().map(group=><tr key={group.id}>{group.headers.map(header=><th key={header.id} scope="col" aria-sort={header.column.getIsSorted()==='asc'?'ascending':header.column.getIsSorted()==='desc'?'descending':undefined}>
        {header.isPlaceholder ? null : header.column.getCanSort() ? <button type="button" onClick={header.column.getToggleSortingHandler()}>{flexRender(header.column.columnDef.header,header.getContext())} <span aria-hidden="true">{header.column.getIsSorted()==='asc'?'↑':header.column.getIsSorted()==='desc'?'↓':'↕'}</span></button> : flexRender(header.column.columnDef.header,header.getContext())}
      </th>)}</tr>)}</thead><tbody>{table.getRowModel().rows.map(row=><tr key={row.id} onClick={event=>{
        // Keep pointer row selection, with one explicit keyboard action per row.
        if ((event.target as HTMLElement).closest('button,a,input,select,summary')) return;
        onSelect?.(row.original);
      }} style={{cursor:onSelect?'pointer':undefined}}>{row.getVisibleCells().map((cell,index)=><td key={cell.id}>{onSelect && index===0 ? <button type="button" className="table-record-button" onClick={()=>onSelect(row.original)}>{flexRender(cell.column.columnDef.cell,cell.getContext())}</button> : flexRender(cell.column.columnDef.cell,cell.getContext())}</td>)}</tr>)}</tbody></table>
    </div>
    {!table.getRowModel().rows.length&&<p className="muted">{data.length?'No matching records. Clear the search or filter to see all records.':'No records yet. Follow the guide to add your first record.'}</p>}
  </>;
}
