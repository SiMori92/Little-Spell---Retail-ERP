import { createHash, timingSafeEqual } from 'node:crypto';
import { z } from 'zod';
import { resolve } from 'node:path';
import { DomainError } from '../domain/errors';

export const hostedEnvironmentSchema=z.object({
 ERP_ACCESS_USERNAME:z.string().min(1).max(80).regex(/^[a-zA-Z0-9_-]+$/).default('founder'),
 ERP_ACCESS_PASSWORD:z.string().min(24),
 ERP_PUBLIC_ORIGIN:z.url().refine(value=>{const url=new URL(value);return url.protocol==='https:'&&!url.username&&!url.password&&url.pathname==='/'&&!url.search&&!url.hash;},'Configure the public HTTPS origin.'),
 ERP_DATA_DIR:z.string().startsWith('/'),
 RAILWAY_VOLUME_MOUNT_PATH:z.string().startsWith('/')
}).refine(value=>{const mount=resolve(value.RAILWAY_VOLUME_MOUNT_PATH),directory=resolve(value.ERP_DATA_DIR);return mount!=='/'&&(directory===mount||directory.startsWith(`${mount}/`));},'The record directory must be on the persistent volume.');
export const isHosted=()=>process.env.ERP_DEPLOYMENT==='railway'||Boolean(process.env.RAILWAY_ENVIRONMENT_ID);
export function hostedEnvironment(){return hostedEnvironmentSchema.parse({...process.env,ERP_PUBLIC_ORIGIN:process.env.ERP_PUBLIC_ORIGIN??(process.env.RAILWAY_PUBLIC_DOMAIN?`https://${process.env.RAILWAY_PUBLIC_DOMAIN}`:undefined)});}
export function validCredentials(authorization:string|null,username:string,password:string):boolean{
 if(!authorization||authorization.length>4096)return false;
 const match=/^Basic ([A-Za-z0-9+/=]+)$/i.exec(authorization);if(!match)return false;
 const supplied=Buffer.from(match[1]!,'base64').toString('utf8'),expected=`${username}:${password}`;
 const hash=(value:string)=>createHash('sha256').update(value).digest();
 return timingSafeEqual(hash(supplied),hash(expected));
}
export function assertHostedRequest(request:Request):void{
 const env=hostedEnvironment(),expected=new URL(env.ERP_PUBLIC_ORIGIN),host=request.headers.get('host')??new URL(request.url).host;
 if(host!==expected.host)throw new DomainError('request','Open the configured Little Spell address.');
 if(!validCredentials(request.headers.get('authorization'),env.ERP_ACCESS_USERNAME,env.ERP_ACCESS_PASSWORD))throw new DomainError('request','Sign in before opening this workspace.');
 const origin=request.headers.get('origin');
 if(origin&&origin!==expected.origin||request.headers.get('sec-fetch-site')==='cross-site')throw new DomainError('request','Reload Little Spell before trying again.');
 if(!['GET','HEAD','OPTIONS'].includes(request.method)&&origin!==expected.origin)throw new DomainError('request','Submit this form from your signed-in Little Spell page.');
}
