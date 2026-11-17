import { handleSellingRequest } from '@/server/selling-api';
export const runtime='nodejs';
export const dynamic='force-dynamic';
export async function POST(request:Request){return handleSellingRequest(request,false);}
