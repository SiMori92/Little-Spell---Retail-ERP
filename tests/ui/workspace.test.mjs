import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createArtworkShuffler, artworkForVisit, artworkStorageKey } from '../../static/js/workspace.mjs';

const artworks = ['a','b','c','d'].map(id => ({ id }));
function session() {
  const values = new Map();
  return { getItem:key=>values.get(key) ?? null, setItem:(key,value)=>values.set(key,value) };
}

test('each bag contains all works and never immediately repeats at its boundary', () => {
  const storage=session(), next=createArtworkShuffler(artworks, ()=>0.999);
  let last;
  for (let cycle=0; cycle<100; cycle++) {
    const bag=[];
    for(let i=0;i<artworks.length;i++) {
      const art=next(storage); assert.notEqual(art.id,last); last=art.id; bag.push(art.id);
    }
    assert.equal(new Set(bag).size,artworks.length);
  }
});

test('unfinished bag survives reload into a new controller', () => {
  const storage=session();
  const ids=artworks.map(()=>createArtworkShuffler(artworks)(storage).id);
  assert.equal(new Set(ids).size,artworks.length);
  assert.notEqual(createArtworkShuffler(artworks)(storage).id,ids.at(-1));
});

test('corrupt or blocked storage cannot prevent artwork selection', () => {
  for (const value of ['{broken','null','[]',JSON.stringify({remaining:['x'],last:null}),JSON.stringify({remaining:['a','a'],last:null}),JSON.stringify({remaining:['a'],last:'a'})]) {
    const storage=session(); storage.setItem(artworkStorageKey,value);
    assert.ok(artworks.includes(createArtworkShuffler(artworks)(storage)));
  }
  const blocked={getItem(){throw Error();},setItem(){throw Error();}};
  const next=createArtworkShuffler(artworks);
  assert.equal(new Set(artworks.map(()=>next(blocked).id)).size,artworks.length);
});

test('query-only navigation retains art; reload, route change and history advance it', () => {
  const storage=session(),next=createArtworkShuffler(artworks,()=>0.999);
  const visit=(pathname,search,navigationType='navigate')=>artworkForVisit({artworks,next,storage,pathname,search,navigationType});
  const first=visit('/reports/','?period=2025-03');
  const bag=storage.getItem(artworkStorageKey);
  assert.equal(visit('/reports/','?period=2025-04').id,first.id);
  assert.equal(storage.getItem(artworkStorageKey),bag);
  const refreshed=visit('/reports/','?period=2025-04','reload');
  assert.notEqual(refreshed.id,first.id);
  const routed=visit('/','');assert.notEqual(routed.id,refreshed.id);
  assert.notEqual(visit('/reports/','?period=2025-04','back_forward').id,routed.id);
});
