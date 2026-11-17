import { handleMasterRequest } from '@/server/master-api';
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
export async function POST(request: Request) { return handleMasterRequest(request,true,true); }
