import { execFileSync } from 'node:child_process';
import { pathToFileURL } from 'node:url';

export function violations(filename: string, content: string): string[] {
  const rules: string[] = [];
  const normalized = filename.toLowerCase();
  if (/(^|\/)(data(?:\.sample-archive-[^/]+|\.restore-[^/]+)?|backups|inbox|state|\.tools)(\/|$)/.test(normalized)) rules.push('private-directory');
  if (/(^|\/)\.env/.test(normalized)) rules.push('env-file');
  if (/(^|\/)(node_modules|\.next|__pycache__)(\/|$)|\.pyc$/.test(normalized)) rules.push('generated-file');
  if (/\.(csv|xlsx|xls)$/.test(normalized) && !/^seed\/.*sample_.*\.csv$/.test(normalized)) rules.push('tabular-file');
  if (content.includes('@') && /[A-Z0-9._%+-]{1,64}@[A-Z0-9.-]{1,253}\.[A-Z]{2,63}/i.test(content)) rules.push('email-content');
  if (content.split('\n').some((line) => /\d{3,}/.test(line) && /\b(?:Road|Rd|Street|St|Lane|Ln|Ave)\b|[號路街巷]/i.test(line))) rules.push('address-content');
  if (/\b(?:sk|pk)_(?:live|test)_[a-z0-9]{12,}|\bsk-[a-z0-9_-]{20,}|\bgh[pousr]_[a-z0-9]{20,}|\bAKIA[A-Z0-9]{16}\b|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----/i.test(content)) rules.push('secret-content');
  if (/\b[a-z0-9_-]*(?:api[_-]?key|access[_-]?token|secret|password)[a-z0-9_-]*["']?\s*[:=]\s*["']?[a-z0-9_+\/-]{16,}/i.test(content)) rules.push('credential-content');
  if (/\bBearer[ \t]+[a-z0-9._~+\/-]{16,}|\beyJ[a-z0-9_-]{8,}\.[a-z0-9_-]{8,}\.[a-z0-9_-]{8,}\b/i.test(content)) rules.push('token-content');
  return rules;
}

export function checkRepository(mode: 'staged' | 'tracked' = 'staged'): boolean {
  const git = (...args: string[]) => execFileSync('git', args, { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] });
  const filenames = git(...(mode === 'tracked' ? ['ls-files', '-z'] : ['diff', '--cached', '--name-only', '--diff-filter=ACMR', '-z'])).split('\0').filter(Boolean);
  let passed = true;
  for (const filename of filenames) {
    let rules: string[];
    try { rules = violations(filename, git('show', `:${filename}`)); }
    catch { rules = ['content-unreadable']; }
    for (const rule of rules) { console.error(`Rejected [${rule}] ${JSON.stringify(filename)}`); passed = false; }
  }
  return passed;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try { process.exitCode = checkRepository(process.argv.includes('--tracked') ? 'tracked' : 'staged') ? 0 : 1; }
  catch { console.error('Repository guard could not inspect the index. Commit blocked.'); process.exitCode = 1; }
}
