// @vitest-environment jsdom
// Runs the inline anti-flash script from index.html against stubbed storage
// and OS settings, so it stays in step with ThemeContext (light by default).
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import indexHtml from '../../index.html?raw'

const script = /<script>([\s\S]*?)<\/script>/.exec(indexHtml)[1]

function run({ stored, osDark, storageThrows = false }) {
  if (storageThrows) {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('SecurityError') })
  } else if (stored !== undefined) {
    localStorage.setItem('tp_theme', stored)
  }
  window.matchMedia = vi.fn(() => ({ matches: osDark }))
  new Function(script)()
  return {
    dark: document.documentElement.classList.contains('dark'),
    scheme: document.documentElement.style.colorScheme,
    meta: document.querySelector('meta[name="theme-color"]').getAttribute('content'),
  }
}

describe('index.html anti-flash script', () => {
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
