// Build plugin: writes dist/sw-assets.json, the list public/sw.js precaches
// when a user saves an offline pack. Every emitted .js/.css file under
// assets/ (the entry, lazy chunks, the per-language locale chunks), without
// source maps or files over 2 MB.
const SHELL = ['/', '/index.html', '/theme-init.js', '/favicon.svg', '/manifest.webmanifest']
const MAX_BYTES = 2 * 1024 * 1024

function sizeOf(item) {
  if (item.type === 'chunk') return Buffer.byteLength(item.code || '')
  const src = item.source
  return typeof src === 'string' ? Buffer.byteLength(src) : (src?.byteLength || 0)
}

export function swAssetsPlugin({ version } = {}) {
  return {
    name: 'voyager-sw-assets',
    apply: 'build',
    generateBundle(_options, bundle) {
      const assets = Object.entries(bundle)
        .filter(([fileName]) => fileName.startsWith('assets/') && /\.(js|css)$/.test(fileName))
        .filter(([, item]) => sizeOf(item) <= MAX_BYTES)
        .map(([fileName]) => `/${fileName}`)
        .sort()
      this.emitFile({
        type: 'asset',
        fileName: 'sw-assets.json',
        source: JSON.stringify({ version: String(version || 'dev'), shell: SHELL, assets }, null, 1),
      })
    },
  }
}
