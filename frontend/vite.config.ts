import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    allowedHosts: true,
    proxy: {
      // Browser never talks to the API directly – Vite proxies /api to FastAPI.
      '/api': { target: process.env.API_URL || 'http://127.0.0.1:8000', changeOrigin: true },
      '/media': { target: process.env.API_URL || 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
  preview: { host: '0.0.0.0', port: 5173, allowedHosts: true },
  build: { outDir: 'dist', sourcemap: false },
})
