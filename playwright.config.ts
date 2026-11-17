import { defineConfig, devices } from '@playwright/test';
const port = process.env.ERP_E2E_PORT ?? '3217';
const baseURL = `http://127.0.0.1:${port}`;
export default defineConfig({
  timeout:60000,
  testDir:'./tests/e2e', fullyParallel:false, workers:1,
  use:{baseURL,trace:'off',screenshot:'off'},
  projects:[{name:'chromium',use:{...devices['Desktop Chrome']}}],
  webServer:{command:'tsx --conditions=react-server tests/e2e-server.ts',url:baseURL,reuseExistingServer:false,timeout:120000,env:{ERP_DATA_DIR:'.tools/e2e-data',PORT:port,NEXT_TELEMETRY_DISABLED:'1'}}
});
