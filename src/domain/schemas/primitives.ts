import { z } from 'zod';
export const decimalSchema = z.string().regex(/^-?(?:0|[1-9]\d{0,13})(?:\.\d{1,4})?$/, {error:'Use a decimal amount with up to four decimal places.',abort:true}).brand<'Money'>();
export type Money = z.infer<typeof decimalSchema>;
export const dateSchema = z.iso.date();
export const datasetSchema = z.enum(['SAMPLE', 'ACTUAL']);
export const hashSchema = z.string().regex(/^[a-f0-9]{64}$/);
export const idSchema = z.uuid();
