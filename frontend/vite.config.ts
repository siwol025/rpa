/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // mock을 끄면 /api 요청을 로컬 백엔드로 넘긴다 (백엔드 주소가 다르면 VITE_PROXY_TARGET으로 바꾼다)
  server: { port: 5173, proxy: { '/api': process.env.VITE_PROXY_TARGET ?? 'http://localhost:8000' } },
  test: {
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    globals: true,
    css: false,
  },
})
