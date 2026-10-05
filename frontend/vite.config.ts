import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import {loadEnv} from 'vite';

export default defineConfig(({mode})=>({
  plugins: [react()],
  server: {port: 5173, strictPort: true, proxy: {'/api': process.env.API_PROXY || `http://127.0.0.1:${loadEnv(mode, '..', '').APP_PORT || '8000'}`}},
  test: {environment: 'jsdom', setupFiles: ['./src/test-setup.ts'], include: ['src/**/*.test.tsx']},
}));
