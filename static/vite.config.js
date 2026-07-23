import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  root: '.',
  base: '/static/',
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:7860',
      '/ws': { target: 'ws://localhost:7860', ws: true },
      '/assets': 'http://localhost:7860',
      '/output': 'http://localhost:7860',
    }
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  }
})