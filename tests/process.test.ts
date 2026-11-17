import { expect, test } from 'vitest';
import { spawn } from 'node:child_process';
import { mkdir, readdir } from 'node:fs/promises';
import { resolve, join } from 'node:path';
import { workspace } from './helpers';
const worker=resolve('tests/write-worker.ts');
function child(directory:string, mode:string, key:string) {
  return spawn(process.execPath,['--import','tsx','--conditions=react-server',worker,directory,mode,key],{stdio:['ignore','ignore','ignore','ipc']});
}
test('R-9 lockfile serializes separate operating-system processes',async()=>{
  const {store,cleanup}=await workspace();
  try {
    const codes=await Promise.all(Array.from({length:4},()=>new Promise<number|null>((resolve,reject)=>{const process=child(store.directory,'normal','cross-process-same-key');process.on('error',reject);process.on('exit',resolve);}))); 
    expect(codes.every(code=>code===0)).toBe(true);expect((await store.read()).length).toBe(1);
  } finally{await cleanup();}
});
test('R-2 twenty SIGKILLs after temp-file creation leave zero partial run files',async()=>{
  const {store,cleanup}=await workspace();const now=new Date().toISOString();const month=join(store.directory,'runs',now.slice(0,4),now.slice(5,7));await mkdir(month,{recursive:true});
  try {
    for(let attempt=0;attempt<20;attempt++) {
      let observed=false;
      const process=child(store.directory,'crash',`crash-${attempt}`);
      process.on('message',message=>{if(message==='half-written'){observed=true;process.kill('SIGKILL');}});
      const timeout=setTimeout(()=>process.kill('SIGKILL'),15000);
      const signal=await new Promise<NodeJS.Signals|null>((resolve,reject)=>{process.on('exit',(_code,signal)=>resolve(signal));process.on('error',reject);});
      clearTimeout(timeout);expect(observed).toBe(true);
      expect(signal).toBe('SIGKILL');
      const lock=await import('node:fs/promises');
      const lockPath=`${store.directory}.lock`;
      try { await lock.utimes(lockPath,new Date(0),new Date(0)); } catch(error) { if (!(error instanceof Error && 'code' in error && error.code==='ENOENT')) throw error; }
      const history=await store.read();expect(history.length<=attempt+1).toBe(true);
      expect((await readdir(month)).filter(name=>name.endsWith('.json')).length).toBe(history.length);
    }
  } finally{await cleanup();}
},180000);
