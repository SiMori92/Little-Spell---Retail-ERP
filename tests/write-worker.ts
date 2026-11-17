import 'server-only';
import { RunStore } from '../src/server/store';
import { journalCandidate } from './helpers';
import fs from 'node:fs/promises';
import { syncBuiltinESMExports } from 'node:module';
const directory=process.argv[2];
if(!directory)throw new Error('Missing test directory.');
const store=new RunStore(directory);
if(process.argv[3]==='crash') {
  process.on('message',()=>{});
  const nativeOpen=fs.open;
  fs.open=async(...args:Parameters<typeof fs.open>)=>{
    const handle=await nativeOpen(...args);
    if(String(args[0]).endsWith('.tmp')) {
      const nativeWrite=handle.writeFile.bind(handle);
      handle.writeFile=async(data)=>{
        const bytes=typeof data==='string'?Buffer.from(data):data instanceof Uint8Array?Buffer.from(data):null;
        if(!bytes)throw new Error('Unexpected synthetic write format.');
        await nativeWrite(bytes.subarray(0,Math.floor(bytes.length/2)));
        process.send?.('half-written');
        await new Promise<void>(()=>{});
      };
    }
    return handle;
  };
  syncBuiltinESMExports();
}
await store.execute(()=>journalCandidate({input:{syntheticPadding:'x'.repeat(process.argv[3]==='crash'?8*1024*1024:1)},idempotencyKey:process.argv[4]??'shared-process-key'}));
