import {defineConfig, devices} from '@playwright/test';

export default defineConfig({
  testDir:'./e2e', timeout:60000, workers:1,
  use:{...devices['Desktop Edge'],channel:'msedge',baseURL:'http://127.0.0.1:5174',trace:'retain-on-failure'},
  webServer:[
    {command:'python -m uvicorn backend.tests.e2e_server:app --host 127.0.0.1 --port 8001',cwd:'..',url:'http://127.0.0.1:8001/api/health',reuseExistingServer:false,timeout:60000},
    {command:'npm run dev -- --port 5174',env:{API_PROXY:'http://127.0.0.1:8001'},url:'http://127.0.0.1:5174',reuseExistingServer:false,timeout:60000},
  ],
});
