import { handleProcurementRequest } from '@/server/procurement-api';
export const runtime='nodejs';
export const dynamic='force-dynamic';
export async function POST(request:Request){return handleProcurementRequest(request,false);}
