import 'server-only';
import assert from 'node:assert/strict';
import { spawn,type ChildProcess } from 'node:child_process';
import { mkdir,mkdtemp,writeFile,stat } from 'node:fs/promises';
import { join,resolve } from 'node:path';
import { randomBytes,randomUUID } from 'node:crypto';
import { initializeWorkspace } from '../src/server/initialize';
await mkdir(resolve('.tools/hosted-smoke'),{recursive:true});
const root=await mkdtemp(join(resolve('.tools/hosted-smoke'),'run-')),directory=join(root,'records'),port='3251',url=`http://127.0.0.1:${port}`,origin=`https://127.0.0.1:${port}`;
const password=randomBytes(32).toString('hex'),authorization=`Basic ${Buffer.from(`founder:${password}`).toString('base64')}`;
const env={...process.env,ERP_DEPLOYMENT:'railway',ERP_PUBLIC_ORIGIN:origin,ERP_ACCESS_USERNAME:'founder',ERP_ACCESS_PASSWORD:password,ERP_DATA_DIR:directory,RAILWAY_VOLUME_MOUNT_PATH:root,PORT:port,NEXT_TELEMETRY_DISABLED:'1'};
const result:Record<string,unknown>={status:'RUNNING',scope:'Native production HTTP adapter; TLS and real Railway volume require live verification'};
const blocked=spawn(process.execPath,['--import','tsx','--conditions=react-server','scripts/start.ts','start'],{env:{...env,ERP_DATA_DIR:join(root,'blocked-records')},stdio:'ignore'});
await new Promise<void>((done,reject)=>{blocked.once('error',reject);blocked.once('exit',code=>{if(code===0)reject(Error('Unconfigured hosted startup unexpectedly succeeded.'));else done();});});
assert.equal(await stat(join(root,'blocked-records')).then(()=>true,()=>false),false);result.ephemeralStartupRefused=true;
await initializeWorkspace(directory);
let child:ChildProcess|null=null;
async function stop(){if(child&&child.exitCode===null)await new Promise<void>(done=>{child!.once('exit',()=>done());child!.kill('SIGTERM');});child=null;}
async function start(){child=spawn(process.execPath,['node_modules/next/dist/bin/next','start','--hostname','127.0.0.1','--port',port],{env,stdio:'ignore'});const deadline=Date.now()+60000;while(Date.now()<deadline){if(child.exitCode!==null)throw Error('Native hosted smoke server exited.');try{if((await fetch(`${url}/healthz`)).ok)return;}catch{}await new Promise(done=>setTimeout(done,100));}throw Error('Native hosted smoke readiness timed out.');}
try{
 await start();const health=await fetch(`${url}/healthz`);assert.deepEqual(await health.json(),{ok:true});result.publicHealth=true;
 const denied=await fetch(url);assert.equal(denied.status,401);assert.match(denied.headers.get('www-authenticate')??'',/Basic/);assert.equal((await fetch(`${url}/api/system/status`)).status,401);result.privatePagesAndApi=true;
 const page=await fetch(`${url}/money`,{headers:{authorization}});assert.equal(page.status,200);assert.match(await page.text(),/Money/);assert.equal(page.headers.get('x-frame-options'),'DENY');result.authenticatedPage=true;
 const status=async()=>{const response=await fetch(`${url}/api/system/status`,{headers:{authorization}});assert.equal(response.status,200);return response.json();};
 const before=await status();const input={action:'manual',occurredOn:new Date().toLocaleDateString('en-CA',{timeZone:'Asia/Taipei'}),idempotencyKey:randomUUID(),record:{eventType:'owner.funds_moved',amount:'10.0000',fundsType:'capital'},evidenceRef:'synthetic-hosted-adapter-voucher'};
 const send=(body:unknown,requestOrigin:string,preview=false)=>fetch(`${url}/api/money/record${preview?'/preview':''}`,{method:'POST',headers:{authorization,origin:requestOrigin,'Content-Type':'application/json'},body:JSON.stringify(body)});
 assert.equal((await send(input,'https://wrong.example.invalid',true)).status,409);result.crossOriginRefused=true;
 const preview=await(await send(input,origin,true)).json();assert.equal(preview.ok,true);assert.equal((await status()).runCount,before.runCount);result.previewNewRuns=0;
 const posted=await(await send({...input,expectedHeadHash:preview.headHash},origin)).json();assert.equal(posted.ok,true);assert.equal((await status()).runCount,before.runCount+1);result.authenticatedWrite=true;
 await stop();await start();assert.equal((await status()).runCount,before.runCount+1);result.recordsSurviveRestart=true;result.status='PASS';
}finally{await stop();await writeFile('.tools/railway-hosted-smoke.json',JSON.stringify(result,null,2)+'\n');}
console.log(JSON.stringify(result));
