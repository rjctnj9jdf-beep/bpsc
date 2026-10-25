import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Сборка кладётся прямо в ../static — FastAPI раздаёт её как есть (Node.js для запуска не нужен).
export default defineConfig({
  plugins: [react()],
  build: { outDir: '../static', emptyOutDir: true },
  server: { port: 5173, proxy: { '/api': 'http://127.0.0.1:8000' } },
})
