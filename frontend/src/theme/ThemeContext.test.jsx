// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { ThemeProvider, useTheme } from './ThemeContext'
import { readTheme, writeTheme, THEME_KEY } from './themeStorage'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

function mockMatchMedia(initialDark) {
  const listeners = new Set()
  const mql = {
    matches: initialDark,
    media: '(prefers-color-scheme: dark)',
    addEventListener: (_t, fn) => listeners.add(fn),
    removeEventListener: (_t, fn) => listeners.delete(fn),
  }
  window.matchMedia = vi.fn(() => mql)
  return {
    set(dark) {
      mql.matches = dark
      listeners.forEach((fn) => fn({ matches: dark }))
    },
  }
}

describe('ThemeProvider', () => {
  let container, root, theme, meta

  function Harness() {
    theme = useTheme()
    return null
  }
  const render = () => act(() => root.render(<ThemeProvider><Harness /></ThemeProvider>))

  beforeEach(() => {
    localStorage.clear()
    document.documentElement.className = ''
    document.documentElement.style.colorScheme = ''
    meta = document.createElement('meta')
    meta.name = 'theme-color'
    meta.content = '#ffffff'
    document.head.appendChild(meta)
    container = document.createElement('div')
    root = createRoot(container)
  })

  afterEach(() => {
    act(() => root.unmount())
    meta.remove()
    vi.restoreAllMocks()
  })

  it('defaults to system and follows a light OS', () => {
    mockMatchMedia(false)
    render()
    expect(theme.theme).toBe('system')
    expect(theme.resolved).toBe('light')
    expect(document.documentElement.classList.contains('dark')).toBe(false)
    expect(document.documentElement.style.colorScheme).toBe('light')
    expect(meta.content).toBe('#ffffff')
  })

  it('system follows the OS setting live', () => {
    const mm = mockMatchMedia(false)
    render()
    act(() => mm.set(true))
    expect(theme.resolved).toBe('dark')
    expect(document.documentElement.classList.contains('dark')).toBe(true)
    act(() => mm.set(false))
    expect(document.documentElement.classList.contains('dark')).toBe(false)
  })

  it("setTheme('dark') adds html.dark, sets colour-scheme and theme-color, and persists", () => {
    mockMatchMedia(false)
    render()
    act(() => theme.setTheme('dark'))
    expect(theme.theme).toBe('dark')
    expect(theme.resolved).toBe('dark')
    expect(document.documentElement.classList.contains('dark')).toBe(true)
    expect(document.documentElement.style.colorScheme).toBe('dark')
    expect(meta.content).not.toBe('#ffffff')
    expect(localStorage.getItem(THEME_KEY)).toBe('dark')
  })

  it("an explicit 'light' ignores a dark OS", () => {
    mockMatchMedia(true)
    localStorage.setItem(THEME_KEY, 'light')
    render()
    expect(theme.theme).toBe('light')
    expect(document.documentElement.classList.contains('dark')).toBe(false)
  })

  it('restores a saved choice', () => {
    mockMatchMedia(false)
    localStorage.setItem(THEME_KEY, 'dark')
    render()
    expect(theme.theme).toBe('dark')
    expect(document.documentElement.classList.contains('dark')).toBe(true)
  })

  it('ignores unknown values', () => {
    mockMatchMedia(false)
    render()
    act(() => theme.setTheme('sepia'))
    expect(theme.theme).toBe('system')
  })

  it('works in memory when localStorage throws (Safari private mode)', () => {
    mockMatchMedia(false)
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('SecurityError') })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('QuotaExceededError') })
    render()
    expect(theme.theme).toBe('system')
    act(() => theme.setTheme('dark'))
    expect(theme.theme).toBe('dark')
    expect(document.documentElement.classList.contains('dark')).toBe(true)
  })

  it('works without matchMedia', () => {
    window.matchMedia = undefined
    render()
    expect(theme.resolved).toBe('light')
  })
})

describe('themeStorage', () => {
  it('swallows storage errors', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('x') })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('x') })
    expect(readTheme()).toBe('system')
    expect(() => writeTheme('dark')).not.toThrow()
    vi.restoreAllMocks()
  })
})
