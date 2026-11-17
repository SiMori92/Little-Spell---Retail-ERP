import 'server-only';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { z } from 'zod';
import { allowLocalRequest,errorResponse } from '@/server/http';
export const runtime='nodejs';
export const dynamic='force-dynamic';
const kindSchema=z.enum(['po','grn','inv','counts']);
const paths={po:'sent/SAMPLE_po_PO-2026-003.csv',grn:'SAMPLE_grn_PO-2026-003_R1.csv',inv:'SAMPLE_inv_EP-2026-0129.csv',counts:'uat/SAMPLE_count_2026-10-04.csv'} as const;
export async function GET(request:Request){try{allowLocalRequest(request);const kind=kindSchema.parse(new URL(request.url).searchParams.get('kind'));const path=paths[kind];return new Response(await readFile(resolve('seed/samples',path),'utf8'),{headers:{'Content-Type':'text/csv;charset=utf-8','Content-Disposition':`attachment; filename="${path.split('/').at(-1)}"`,'Cache-Control':'no-store'}});}catch(error){return errorResponse(error);}}
