import Decimal from './decimal';
import { decimalSchema, type Money } from './schemas';
export const money = (value: string): Money => decimalSchema.parse(new Decimal(value).toFixed(4));
export const sumMoney = (values: readonly Money[]): Money => money(values.reduce((total, value) => total.plus(value), new Decimal(0)).toFixed(4));
