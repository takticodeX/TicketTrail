/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// In development the Vite server proxies /api to the backend, like Nginx does in production.
const apiTarget = process.env.VITE_API_PROXY ?? 'http://127.0.0.1:8000';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 8080,
    host: true,
    proxy: { '/api': { target: apiTarget, changeOrigin: false } },
    // Bind mounts from Windows into the Podman VM don't deliver file events.
    watch: process.env.VITE_POLL ? { usePolling: true, interval: 300 } : undefined,
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    restoreMocks: true,
  },
});
