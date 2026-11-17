import { handleActivation } from '@/server/activation-api';
export const runtime='nodejs';
export const dynamic='force-dynamic';
export async function POST(request:Request){return handleActivation(request,true);}
