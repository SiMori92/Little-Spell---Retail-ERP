import { activationPayloadSchema } from './schemas/activation';
import { accountLeg,datasetOf,stableId } from './accounting';
import { journalSchema,type Run,type Candidate } from './schemas';
import { DomainError } from './errors';
import { canonical } from './canonical';
export function planActivation(raw:unknown,runs:readonly Run[]):Candidate{
 const input=activationPayloadSchema.parse(raw),existing=runs.find(r=>r.idempotencyKey===input.idempotencyKey);
 if(existing){if(canonical(existing.input)!==canonical(input))throw new DomainError('idempotencyKey','This request key was already used.');return {kind:existing.kind,dataset:existing.dataset,occurredOn:existing.occurredOn,idempotencyKey:existing.idempotencyKey,input:existing.input,effects:existing.effects};}
 if(datasetOf(runs)!=='SAMPLE')throw new DomainError('dataset','Actual data is already active.');
 if(input.expectedHeadHash&&input.expectedHeadHash!==(runs.at(-1)?.hash??'0'.repeat(64)))throw new DomainError('expectedHeadHash','History changed. Preview the transition again.');
 if(input.action==='actual-opening'){
  if(runs.some(r=>r.dataset==='ACTUAL'&&r.effects.some(e=>e.type==='journal.posted'&&e.opening==='REAL_OPENING')))throw new DomainError('opening','A real opening entry is already recorded.');
  if(input.lines.some(l=>l.account.startsWith('123')))throw new DomainError('lines','Record real stock through its complete physical count after activation. This opening schedule covers non-stock balances.');
  const entry=journalSchema.parse({entryId:stableId(['real-opening',input.evidenceRef]),occurredOn:input.occurredOn,sourceEvent:'opening.balances',lines:input.lines.map(l=>accountLeg(l.account,l.debit,l.credit,{sourceRef:input.evidenceRef}))});
  return {kind:'dataset.opening',dataset:'ACTUAL',occurredOn:input.occurredOn,idempotencyKey:input.idempotencyKey,input,effects:[{type:'journal.posted',entry,opening:'REAL_OPENING',founderAuthorization:input.founderAuthorization}]};
 }
 return {kind:'dataset.activate',dataset:'SAMPLE',occurredOn:input.occurredOn,input,idempotencyKey:input.idempotencyKey,effects:[{type:'dataset.activated'}]};
}
export function validateActivation(candidate:Candidate,runs:readonly Run[]){if(canonical(planActivation(candidate.input,runs))!==canonical(candidate))throw new DomainError('opening','Opening balances must match the reviewed schedule.');}
