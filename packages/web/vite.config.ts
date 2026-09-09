import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// `base: './'` keeps every asset URL relative, so the same build works at the
// domain root and under a GitHub Pages repository path such as
// https://user.github.io/parametric_cad_tray/ with no rebuild.
export default defineConfig({
  base: './',
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true } },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./tests/setup.ts'],
    globals: true,
    css: false,
  },
})
