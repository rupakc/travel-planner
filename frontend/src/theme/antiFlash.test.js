// @vitest-environment jsdom
// Runs public/theme-init.js (the render-blocking anti-flash script) against
// stubbed storage and OS settings, so it stays in step with ThemeContext
// (light by default). Also guards index.html against inline scripts, which the
// production CSP (`script-src 'self'`, deploy/gcp/Caddyfile) blocks.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import themeInit from '../../public/theme-init.js?raw'
import indexHtml from '../../index.html?raw'

function run({ stored, osDark, storageThrows = false }) {
  if (storageThrows) {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('SecurityError') })
  } else if (stored !== undefined) {
    localStorage.setItem('tp_theme', stored)
  }
  window.matchMedia = vi.fn(() => ({ matches: osDark }))
  new Function(themeInit)()
  return {
    dark: document.documentElement.classList.contains('dark'),
    scheme: document.documentElement.style.colorScheme,
    meta: document.querySelector('meta[name="theme-color"]').getAttribute('content'),
  }
}

describe('theme-init.js anti-flash script', () => {
  let meta
  beforeEach(() => {
    localStorage.clear()
    document.documentElement.className = ''
    document.documentElement.style.colorScheme = ''
    meta = document.createElement('meta')
    meta.name = 'theme-color'
    meta.content = '#ffffff'
    document.head.appendChild(meta)
  })
  afterEach(() => {
    meta.remove()
    vi.restoreAllMocks()
  })

  it('is light with no stored value, even on a dark OS, without asking the OS', () => {
    const r = run({ osDark: true })
    expect(r).toEqual({ dark: false, scheme: 'light', meta: '#ffffff' })
    expect(window.matchMedia).not.toHaveBeenCalled()
  })

  it('applies a stored dark choice', () => {
    expect(run({ stored: 'dark', osDark: false })).toEqual({ dark: true, scheme: 'dark', meta: '#121a2b' })
  })

  it("follows the OS only when 'system' is stored", () => {
    expect(run({ stored: 'system', osDark: true }).dark).toBe(true)
  })

  it("'system' on a light OS stays light", () => {
    expect(run({ stored: 'system', osDark: false }).dark).toBe(false)
  })

  it('stays light when localStorage throws', () => {
    expect(run({ storageThrows: true, osDark: true }).dark).toBe(false)
  })
})

describe('index.html (CSP guard)', () => {
  const scripts = [...indexHtml.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi)]
  const head = indexHtml.slice(0, indexHtml.indexOf('</head>'))

  it('has no inline scripts: every <script> has a src and an empty body', () => {
    expect(scripts.length).toBeGreaterThan(0)
    for (const [, attrs, body] of scripts) {
      expect(attrs).toMatch(/\bsrc\s*=/)
      expect(body.trim()).toBe('')
    }
  })

  it('loads /theme-init.js as a render-blocking classic script in <head>, before any stylesheet', () => {
    const tag = /<script src="\/theme-init\.js"><\/script>/.exec(head)
    expect(tag).not.toBeNull()
    const before = head.slice(0, tag.index)
    expect(before).not.toMatch(/rel="stylesheet"/)
    expect(tag[0]).not.toMatch(/\b(async|defer|type=)/)
  })
})
