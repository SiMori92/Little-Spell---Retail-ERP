import { NextResponse,type NextRequest } from 'next/server';
import { hostedEnvironment,isHosted,validCredentials } from './server/hosting';
export function proxy(request:NextRequest){
 if(!isHosted()||request.nextUrl.pathname==='/healthz')return NextResponse.next();
 let env:ReturnType<typeof hostedEnvironment>;
 try{env=hostedEnvironment();}catch{return NextResponse.json({ok:false,errors:[{field:'service',message:'Hosted access and storage are not configured.'}]},{status:503});}
 if(!validCredentials(request.headers.get('authorization'),env.ERP_ACCESS_USERNAME,env.ERP_ACCESS_PASSWORD))return new NextResponse('Sign in to Little Spell.',{status:401,headers:{'WWW-Authenticate':'Basic realm="Little Spell", charset="UTF-8"','Cache-Control':'no-store'}});
 if(request.headers.get('host')!==new URL(env.ERP_PUBLIC_ORIGIN).host)return new NextResponse('Open the configured Little Spell address.',{status:400});
 const response=NextResponse.next();response.headers.set('Cache-Control','private, no-store');response.headers.set('X-Robots-Tag','noindex, nofollow');response.headers.set('Content-Security-Policy',"frame-ancestors 'none'");response.headers.set('X-Frame-Options','DENY');response.headers.set('Referrer-Policy','no-referrer');return response;
}
