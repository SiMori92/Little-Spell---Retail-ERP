import { expect, test } from 'vitest';
import { mkdir, writeFile, rm } from 'node:fs/promises';
import { resolve } from 'node:path';
import ts from 'typescript';
import { violations } from '../scripts/repo-guard';
import { checkMoney } from '../scripts/money-guard';
test('repo guard rejects protected paths, synthetic email/address and credential patterns',()=>{
  expect(violations('data/run.json','{}')).toContain('private-directory');
  expect(violations('src/synthetic.ts',['buyer','invalid.example'].join('@'))).toContain('email-content');
  const syntheticNumber = ['12','3'].join('');
  expect(violations('src/synthetic.ts',[syntheticNumber,'Synthetic','Road'].join(' '))).toContain('address-content');
  expect(violations('src/synthetic.ts',['sk','live','a'.repeat(24)].join('_'))).toContain('secret-content');
  expect(violations('src/synthetic.ts',JSON.stringify({ api_key:'a'.repeat(24) }))).toContain('credential-content');
  expect(violations('src/synthetic.ts',['Bearer','a'.repeat(24)].join(' '))).toContain('token-content');
  expect(violations('seed/samples/SAMPLE_example.csv','sku,qty\nSYNTHETIC,1')).toEqual([]);
});
test('money guard fails planted parseFloat and arithmetic on branded Money',async()=>{
  const directory=resolve('.tools/src');await mkdir(directory,{recursive:true});const filename=resolve(directory,'planted-money.ts');
  await writeFile(filename,`type Money = string & { readonly __brand: 'Money' };\ndeclare const amount: Money;\nparseFloat(amount);\nconst bad = amount + amount;\nconst worse = +amount;\n`);
  try { const errors=checkMoney(ts.createProgram([filename],{strict:true,noEmit:true,target:ts.ScriptTarget.ES2022}));expect(errors.length).toBe(3); }
  finally {await rm(filename);}
});
