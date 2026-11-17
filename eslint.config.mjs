import { defineConfig, globalIgnores } from 'eslint/config';
import nextVitals from 'eslint-config-next/core-web-vitals';
import nextTypescript from 'eslint-config-next/typescript';
export default defineConfig([
  ...nextVitals, ...nextTypescript,
  globalIgnores(['.next/**', '.tools/**', 'data/**', 'coverage/**', 'test-results/**', 'playwright-report/**', 'next-env.d.ts']),
  { files: ['src/**/*.ts', 'src/**/*.tsx'], rules: {
    'no-restricted-syntax': ['error',
      { selector: 'CallExpression[callee.name="parseFloat"]', message: 'Use exact decimal strings, not floating-point conversion.' },
      { selector: 'CallExpression[callee.name="Number"]', message: 'Use validated integers or exact decimal operations.' },
      { selector: 'CallExpression[callee.object.name="Number"][callee.property.name="parseFloat"]', message: 'Use exact decimal operations.' }
    ]
  } }
]);
