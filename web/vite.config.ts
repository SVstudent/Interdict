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
  build: { outDir: 'dist', sourcemap: true },
});
