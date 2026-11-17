import { afterEach,expect,test,vi } from 'vitest';
import { NextRequest } from 'next/server';
import { proxy } from '../src/proxy';
import { allowLocalRequest } from '../src/server/http';
import { hostedEnvironmentSchema,validCredentials } from '../src/server/hosting';
import { volumeIsMounted } from '../src/server/hosted-storage';
const password=['synthetic','railway','access','only'].join('-');
const authorization=`Basic ${Buffer.from(`founder:${password}`).toString('base64')}`;
function host(){vi.stubEnv('ERP_DEPLOYMENT','railway');vi.stubEnv('ERP_PUBLIC_ORIGIN','https://erp.example.invalid');vi.stubEnv('ERP_ACCESS_USERNAME','founder');vi.stubEnv('ERP_ACCESS_PASSWORD',password);vi.stubEnv('ERP_DATA_DIR','/data/erp');vi.stubEnv('RAILWAY_VOLUME_MOUNT_PATH','/data');}
afterEach(()=>vi.unstubAllEnvs());
test('hosted startup configuration requires private access, HTTPS and volume-contained data',()=>{
 const input={ERP_ACCESS_PASSWORD:password,ERP_PUBLIC_ORIGIN:'https://erp.example.invalid',ERP_DATA_DIR:'/data/erp',RAILWAY_VOLUME_MOUNT_PATH:'/data'};
 expect(hostedEnvironmentSchema.safeParse(input).success).toBe(true);
 for(const patch of [{ERP_ACCESS_PASSWORD:''},{ERP_PUBLIC_ORIGIN:'http://erp.example.invalid'},{ERP_DATA_DIR:'/tmp/records'},{ERP_DATA_DIR:'/data/../tmp'},{RAILWAY_VOLUME_MOUNT_PATH:'/'},{ERP_PUBLIC_ORIGIN:'https://erp.example.invalid/subpage'}])expect(hostedEnvironmentSchema.safeParse({...input,...patch}).success).toBe(false);
 expect(volumeIsMounted('84 52 0:42 / /data rw - ext4 /dev/volume rw','/data')).toBe(true);expect(volumeIsMounted('84 52 0:42 / /other rw - ext4 /dev/volume rw','/data')).toBe(false);
});
test('hosted pages challenge unauthenticated clients and fail closed without configuration',()=>{
 host();const request=(path:string,headers:Record<string,string>={})=>new NextRequest(`https://erp.example.invalid${path}`,{headers:{host:'erp.example.invalid',...headers}});
 expect(proxy(request('/')).status).toBe(401);expect(proxy(request('/api/money/records')).headers.get('WWW-Authenticate')).toContain('Basic');expect(proxy(request('/healthz')).status).toBe(200);
 expect(proxy(request('/',{authorization})).headers.get('x-middleware-next')).toBe('1');expect(proxy(request('/',{authorization,host:'wrong.example.invalid'})).status).toBe(400);
 vi.stubEnv('ERP_ACCESS_PASSWORD','');expect(proxy(request('/',{authorization})).status).toBe(503);
});
test('hosted API accepts only authenticated configured-host, same-origin writes',()=>{
 host();const request=(headers:Record<string,string>={})=>new Request('http://0.0.0.0:3000/api/money/record',{method:'POST',headers:{host:'erp.example.invalid',origin:'https://erp.example.invalid',authorization,...headers}});
 expect(()=>allowLocalRequest(request())).not.toThrow();
 for(const headers of [{authorization:''},{origin:'https://wrong.example.invalid'},{origin:''},{host:'wrong.example.invalid'},{'sec-fetch-site':'cross-site'}])expect(()=>allowLocalRequest(request(Object.fromEntries(Object.entries(headers).filter((entry):entry is [string,string]=>typeof entry[1]==='string'))))).toThrow();
});
test('Basic credentials reject malformed and wrong credentials; local mode stays loopback-only',()=>{
 expect(validCredentials(authorization,'founder',password)).toBe(true);expect(validCredentials(authorization,'other',password)).toBe(false);expect(validCredentials('Basic invalid!','founder',password)).toBe(false);expect(validCredentials(null,'founder',password)).toBe(false);
 vi.stubEnv('ERP_DEPLOYMENT','');vi.stubEnv('RAILWAY_ENVIRONMENT_ID','');expect(()=>allowLocalRequest(new Request('http://127.0.0.1:3000/api/system/status'))).not.toThrow();expect(()=>allowLocalRequest(new Request('https://erp.example.invalid/api/system/status'))).toThrow();
});
