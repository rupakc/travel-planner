// @vitest-environment node
import { describe, it, expect, vi } from 'vitest'
import { swAssetsPlugin } from './swAssets'

const chunk = (code) => ({ type: 'chunk', code })
const asset = (source) => ({ type: 'asset', source })

function run(bundle, version = '1.2.3+20261112') {
  const plugin = swAssetsPlugin({ version })
  const emitFile = vi.fn()
  plugin.generateBundle.call({ emitFile }, {}, bundle)
  expect(emitFile).toHaveBeenCalledTimes(1)
  const file = emitFile.mock.calls[0][0]
  expect(file.type).toBe('asset')
  expect(file.fileName).toBe('sw-assets.json')
  return JSON.parse(file.source)
}

describe('swAssetsPlugin', () => {
  it('is a build-only plugin', () => {
    expect(swAssetsPlugin({ version: 'x' }).apply).toBe('build')
  })

  it('lists the js/css chunks and locale chunks, and skips maps and big files', () => {
    const big = 'x'.repeat(2 * 1024 * 1024 + 1)
    const out = run({
      'index.html': asset('<html></html>'),
      'theme-init.js': asset('/* public */'),
      'assets/index-abc123.js': chunk('console.log(1)'),
      'assets/index-abc123.js.map': asset('{}'),
      'assets/index-def456.css': asset('body{}'),
      'assets/de-trips-0a1b2c.js': chunk('export default {}'),
      'assets/huge-999.js': chunk(big),
      'assets/marker-icon-1.png': asset(new Uint8Array(10)),
    })
    expect(out.version).toBe('1.2.3+20261112')
    expect(out.shell).toEqual(['/', '/index.html', '/theme-init.js', '/favicon.svg', '/manifest.webmanifest'])
    expect(out.assets).toEqual([
      '/assets/de-trips-0a1b2c.js',
      '/assets/index-abc123.js',
      '/assets/index-def456.css',
    ])
  })
})
