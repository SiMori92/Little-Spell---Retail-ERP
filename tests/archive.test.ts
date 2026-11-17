import { afterEach, expect, test } from 'vitest';
import { mkdir, readFile, rm, writeFile, chmod } from 'node:fs/promises';
import { join } from 'node:path';
import { backup, restore, resetSample, lastBackup } from '../src/server/archive';
import { RunStore } from '../src/server/store';
import { workspace, journalCandidate } from './helpers';
const cleanups: (()=>Promise<unknown>)[]=[];
afterEach(async()=>{for(const cleanup of cleanups.splice(0))await cleanup();});
test('R-11 backup/restore preserves verified history, attachment bytes, and checksum',async()=>{
  const {store,cleanup}=await workspace();cleanups.push(cleanup);
  await store.execute(()=>journalCandidate());await store.putAttachment(Buffer.from('synthetic-evidence'),'pdf');
  const destination=join(store.directory,'.cache','archives');const archive=await backup(store,destination);
  const target=join(store.directory,'.cache','restored');await restore(archive,target);
  expect((await new RunStore(target).read()).length).toBe(1);expect((await lastBackup(store.directory)).days).toBe(0);
  await expect(restore(archive,target)).rejects.toThrow(/empty/);
  await writeFile(`${archive}.sha256`,'0'.repeat(64));await expect(restore(archive,join(store.directory,'.cache','bad'))).rejects.toThrow(/checksum/);
});
test('reset refuses actual opening records even before activation',async()=>{
  const {store,cleanup}=await workspace();cleanups.push(cleanup);
  const candidate=journalCandidate({dataset:'ACTUAL'});const effect=candidate.effects[0];if(effect?.type!=='journal.posted')throw new Error('fixture');
  effect.opening='REAL_OPENING';effect.founderAuthorization='synthetic-founder-approval';
  await store.execute(()=>candidate);await expect(resetSample(store)).rejects.toThrow(/Actual/);
});
test('backup refuses corrupted evidence before recording success',async()=>{
  const {store,cleanup}=await workspace();cleanups.push(cleanup);
  const sha=await store.putAttachment(Buffer.from('synthetic-original'),'pdf');
  const filename=join(store.directory,'attachments',`${sha}.pdf`);await chmod(filename,0o600);await writeFile(filename,'synthetic-changed');
  await expect(backup(store,join(store.directory,'.cache','archives'))).rejects.toThrow(/evidence/);
  expect((await lastBackup(store.directory)).days).toBeNull();
});
test('backup reminder is unknown until a successful backup, amber after seven days',async()=>{
  const {store,cleanup}=await workspace();cleanups.push(cleanup);expect((await lastBackup(store.directory)).stale).toBe(true);
  await mkdir(join(store.directory,'.cache'),{recursive:true});
  await writeFile(join(store.directory,'.cache','backup.json'),JSON.stringify({createdAt:new Date(Date.now()-8*86400000).toISOString(),sha256:'0'.repeat(64),name:'synthetic.zip'}));
  expect((await lastBackup(store.directory)).stale).toBe(true);expect((await readFile(join(store.directory,'meta.json'),'utf8')).length>0).toBe(true);
  await writeFile(join(store.directory,'.cache','backup.json'),JSON.stringify({createdAt:new Date(Date.now()-7.1*86400000).toISOString(),sha256:'0'.repeat(64),name:'synthetic.zip'}));
  expect((await lastBackup(store.directory)).stale).toBe(true);
  await rm(join(store.directory,'.cache'),{recursive:true});expect((await lastBackup(store.directory)).days).toBeNull();
});
