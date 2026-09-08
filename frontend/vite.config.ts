import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// O backend serve a API em /api. Em desenvolvimento o Vite encaminha para lá,
// e o app abre no celular pela rede local com `--host`.
export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    proxy: {
      '/api': {
        target: process.env.VITE_API_TARGET ?? 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/testes/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
  },
})
