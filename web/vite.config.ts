import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import path from 'node:path';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': path.resolve(__dirname, './src') } },
  server: {
    port: 5173,
    proxy: {
      // SSE needs buffering off; Vite passes text/event-stream straight through.
      '/api': { target: 'http://localhost:8077', changeOrigin: true },
      '/healthz': { target: 'http://localhost:8077', changeOrigin: true },
    },
  },
  // Declared explicitly rather than left to inherit from `server`. The demo is recorded against
  // the production build served by `vite preview`, and a proxy that worked only by inheritance is
  // a silent dependency on Vite's default: the failure mode is the SPA fallback answering /api
  // with index.html, so the console renders an empty world at 200 OK and nothing looks broken
  // until the first click does nothing.
  preview: {
    port: 4173,
    proxy: {
      '/api': { target: 'http://localhost:8077', changeOrigin: true },
      '/healthz': { target: 'http://localhost:8077', changeOrigin: true },
    },
  },
  build: { outDir: 'dist', sourcemap: true },
});
