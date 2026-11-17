import { createHash } from 'node:crypto';
export function canonical(value: unknown): string {
  if (value === null || typeof value !== 'object') {
    const encoded = JSON.stringify(value);
    if (encoded === undefined) throw new Error('Value cannot be serialized.');
    return encoded;
  }
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  return `{${Object.entries(value).sort(([left], [right]) => left < right ? -1 : left > right ? 1 : 0).map(([key, item]) => `${JSON.stringify(key)}:${canonical(item)}`).join(',')}}`;
}
export const digest = (value: unknown): string => createHash('sha256').update(canonical(value)).digest('hex');
