import { handleAccounting } from '@/server/accounting-api';
export const runtime='nodejs';
export const dynamic='force-dynamic';
export async function POST(request:Request){return handleAccounting(request,false,'close');}
