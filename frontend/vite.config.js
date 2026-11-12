/// <reference types="vitest" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { readFileSync } from 'node:fs'
import { swAssetsPlugin } from './vite/swAssets.js'

// Telemetry app_version: VITE_APP_VERSION when the build sets it, else
// <package.json version>+<build date YYYYMMDD>.
const pkg = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf8'))
const buildDate = new Date().toISOString().slice(0, 10).replace(/-/g, '')
const appVersion = process.env.VITE_APP_VERSION || `${pkg.version}+${buildDate}`

export default defineConfig({
  // swAssetsPlugin writes dist/sw-assets.json, the shell + assets list the
  // offline service worker (public/sw.js) precaches.
  plugins: [react(), swAssetsPlugin({ version: appVersion })],
  define: {
    'import.meta.env.VITE_APP_VERSION': JSON.stringify(appVersion),
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.js'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'lcov'],
    },
  },
  server: {
    port: 5174,
    proxy: {
      '/api': {
        target: 'http://localhost:8001',
        changeOrigin: true,
      },
      // /health carries capability flags (e.g. serpapi_configured)
      '/health': {
        target: 'http://localhost:8001',
        changeOrigin: true,
      },
    }
  }
})
