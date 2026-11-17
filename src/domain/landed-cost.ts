import Decimal from './decimal';
import { DomainError } from './errors';
import { landedInputSchema, landedLineSchema, type LandedInput, type LandedLine } from './schemas/procurement';
import { decimalSchema } from './schemas/primitives';

export const exactMoney=(value:InstanceType<typeof Decimal>|string)=>decimalSchema.parse(new Decimal(value).toFixed(4));
export function allocateCharge(total:string,weights:readonly {lineNo:number;value:string}[]):Map<number,string>{
  if(!weights.length||new Set(weights.map(item=>item.lineNo)).size!==weights.length)throw new DomainError('lines','Allocation needs unique receipt line numbers.');
  const basis=weights.reduce((sum,item)=>sum.plus(item.value),new Decimal(0));
  if(basis.lte(0)){if(!new Decimal(total).isZero())throw new DomainError('lines','Charges cannot be allocated over zero-value lines.');return new Map(weights.map(item=>[item.lineNo,'0.0000']));}
  const last=Math.max(...weights.map(item=>item.lineNo)),shares=new Map<number,string>();let allocated=new Decimal(0);
  for(const item of weights)if(item.lineNo!==last){const value=exactMoney(new Decimal(total).times(item.value).div(basis));shares.set(item.lineNo,value);allocated=allocated.plus(value);}
  shares.set(last,exactMoney(new Decimal(total).minus(allocated)));
  return shares;
}
export function valueReceipt(raw:readonly LandedInput[],freight:string,tax:string,creditable:string):LandedLine[]{
  const lines=raw.map(line=>landedInputSchema.parse(line));
  if(new Decimal(freight).isNegative()||new Decimal(tax).isNegative()||new Decimal(creditable).isNegative()||new Decimal(creditable).gt(tax))throw new DomainError('tax','Use non-negative charges and creditable tax within the stated tax.');
  if(lines.some(line=>new Decimal(line.qtyGood).plus(line.qtyDamaged).lte(0)))throw new DomainError('lines','Each valued receipt line must accept pieces.');
  const byValue=lines.map(line=>({lineNo:line.lineNo,value:line.lineAmount})),freightShares=allocateCharge(freight,byValue);
  const stated=lines.filter(line=>line.statedTax!==null);
  if(stated.length&&stated.length!==lines.length)throw new DomainError('tax','Per-line tax must be stated on every line or on none.');
  if(stated.length&&!stated.reduce((sum,line)=>sum.plus(line.statedTax!),new Decimal(0)).eq(tax))throw new DomainError('tax','Stated line taxes do not sum to the invoice tax.');
  const taxShares=allocateCharge(exactMoney(new Decimal(tax).minus(creditable)),stated.length?lines.map(line=>({lineNo:line.lineNo,value:line.statedTax!})):byValue);
  return [...lines].sort((left,right)=>left.lineNo-right.lineNo).map(line=>{
    const landed=new Decimal(line.lineAmount).plus(freightShares.get(line.lineNo)!).plus(taxShares.get(line.lineNo)!);
    const damage=exactMoney(landed.times(line.qtyDamaged).div(new Decimal(line.qtyGood).plus(line.qtyDamaged)));
    return landedLineSchema.parse({...line,freightShare:freightShares.get(line.lineNo),taxShare:taxShares.get(line.lineNo),landed:exactMoney(landed),damagedValue:damage,goodValue:exactMoney(landed.minus(damage))});
  });
}
export function proRataDeposit(deposits:string,receiptValue:string,poValue:string,already:string,completes:boolean):string{
  const remaining=Decimal.max(0,new Decimal(deposits).minus(already));
  if(completes)return exactMoney(remaining);
  if(new Decimal(poValue).lte(0))throw new DomainError('deposit','The purchase order value must be positive.');
  return exactMoney(Decimal.min(remaining,new Decimal(new Decimal(deposits).times(receiptValue).div(poValue).toFixed(4))));
}
