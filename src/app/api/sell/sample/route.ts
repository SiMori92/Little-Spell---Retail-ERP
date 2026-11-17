import 'server-only';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { z } from 'zod';
import { allowLocalRequest, errorResponse } from '@/server/http';
export const runtime='nodejs';
export const dynamic='force-dynamic';
const kindSchema=z.enum(['orderitems','statement','instagram']);
export async function GET(request:Request){try{allowLocalRequest(request);const kind=kindSchema.parse(new URL(request.url).searchParams.get('kind'));const path=kind==='instagram'?'samples/SAMPLE_ig_deals_2026-10.csv':`fixtures/SAMPLE_etsy_${kind}_2025-12_fixture.csv`;return new Response(await readFile(resolve('seed',path),'utf8'),{headers:{'Content-Type':'text/csv;charset=utf-8','Content-Disposition':`attachment; filename="${path.split('/').at(-1)}"`,'Cache-Control':'no-store'}});}catch(error){return errorResponse(error);}}
