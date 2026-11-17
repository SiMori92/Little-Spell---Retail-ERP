import { DomainError } from './errors';

export function parseCsv(source: string): string[][] {
  if (source.length > 524288 || /\u0000|\uFFFD/.test(source)) throw new DomainError('csvText', 'Choose a valid UTF-8 CSV smaller than 512 KB.');
  const text = source.replace(/^\uFEFF/, '');
  const rows: string[][] = [];
  let row: string[] = [], cell = '', state: 'start' | 'plain' | 'quoted' | 'closed' = 'start';
  function finishRow() {
    row.push(cell);
    if (!(row.length === 1 && row[0] === '')) rows.push(row);
    if (rows.length > 5001) throw new DomainError('csvText', 'Import at most 5,000 records at a time.');
    row = []; cell = ''; state = 'start';
  }
  for (let position = 0; position < text.length; position++) {
    const character = text.charAt(position);
    if (state === 'quoted') {
      if (character === '"') {
        if (text.charAt(position + 1) === '"') { cell += '"'; position++; }
        else state = 'closed';
      } else cell += character;
      continue;
    }
    if (character === ',') { row.push(cell); cell = ''; state = 'start'; continue; }
    if (character === '\n' || character === '\r') { finishRow(); if (character === '\r' && text.charAt(position + 1) === '\n') position++; continue; }
    if (state === 'closed') throw new DomainError('csvText', 'Remove unexpected text after a quoted CSV cell.');
    if (character === '"') {
      if (state !== 'start') throw new DomainError('csvText', 'Quote the entire cell when it contains quotation marks.');
      state = 'quoted';
    } else { cell += character; state = 'plain'; }
    if (row.length > 30) throw new DomainError('csvText', 'This file has too many columns. Use the supplied CSV template.');
  }
  if (state === 'quoted') throw new DomainError('csvText', 'Close the quotation marks in the CSV file.');
  if (cell !== '' || row.length || state === 'closed') finishRow();
  return rows;
}

export function csvCell(value: unknown): string {
  const text = String(value ?? '');
  const safe = /^[=+\-@\t\r]/.test(text) ? `'${text}` : text;
  return /[",\r\n]/.test(safe) ? `"${safe.replaceAll('"', '""')}"` : safe;
}
export function serializeCsv(rows: readonly (readonly unknown[])[]): string { return `${rows.map((row) => row.map(csvCell).join(',')).join('\r\n')}\r\n`; }
