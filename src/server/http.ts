import 'server-only';
import { z } from 'zod';
import { DomainError } from '../domain/errors';
import { isHosted,assertHostedRequest } from './hosting';

export function allowLocalRequest(request: Request): void {
  if(isHosted()){assertHostedRequest(request);return;}
  const url = new URL(request.url);
  const loopback = ['127.0.0.1', 'localhost', '[::1]'];
  const host = request.headers.get('host');
  let incoming = url;
  try { if (host) incoming = new URL(`${url.protocol}//${host}`); }
  catch { throw new DomainError('request', 'Open Little Spell on this computer only.'); }
  if (!loopback.includes(url.hostname) || !loopback.includes(incoming.hostname) || incoming.port !== url.port || incoming.username || incoming.password || host && (incoming.pathname !== '/' || incoming.search || incoming.hash)) throw new DomainError('request', 'Open Little Spell on this computer only.');
  const origin = request.headers.get('origin');
  if (origin && origin !== incoming.origin) throw new DomainError('request', 'Reload Little Spell before trying again.');
  if (request.headers.get('sec-fetch-site') === 'cross-site') throw new DomainError('request', 'Reload Little Spell before trying again.');
}

export async function readPayload(request: Request, maximumBytes = 65536): Promise<unknown> {
  allowLocalRequest(request);
  if (!request.headers.get('content-type')?.startsWith('application/json')) throw new DomainError('request', 'Send this form as JSON.');
  const reader = request.body?.getReader();
  if (!reader) throw new DomainError('request', 'Complete the form before continuing.');
  const chunks: Uint8Array[] = [];
  let bytes = 0;
  while (true) {
    const next = await reader.read();
    if (next.done) break;
    bytes += next.value.byteLength;
    if (bytes > maximumBytes) { await reader.cancel(); throw new DomainError('request', 'This form is too large.'); }
    chunks.push(next.value);
  }
  try { return JSON.parse(Buffer.concat(chunks).toString('utf8')); }
  catch { throw new DomainError('request', 'The form could not be read. Check it and try again.'); }
}

export function errorResponse(error: unknown): Response {
  if (error instanceof DomainError) return Response.json({ ok: false, errors: [{ field: error.field, message: error.message }] }, { status: 409 });
  if (error instanceof z.ZodError) return Response.json({ ok: false, errors: error.issues.map((issue) => ({ field: issue.path.map(String).join('.'), message: 'Check this field and enter a valid value.' })) }, { status: 400 });
  return Response.json({ ok: false, errors: [{ field: 'request', message: 'This action could not be completed. No partial record was booked. Please retry.' }] }, { status: 500 });
}
