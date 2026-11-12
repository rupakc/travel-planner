// @vitest-environment jsdom
import { describe, it, expect, afterEach, vi } from 'vitest'
import i18n, { detectLanguage, setLanguage, NAMESPACES, BUNDLED_NAMESPACES, prefetchLazyNamespaces } from './index'

const setNavigatorLanguages = (langs) =>
  vi.spyOn(window.navigator, 'languages', 'get').mockReturnValue(langs)

afterEach(async () => {
  vi.restoreAllMocks()
  try { localStorage.clear() } catch { /* ignore */ }
  await i18n.changeLanguage('en')
})

describe('detectLanguage', () => {
  it('prefers tp_lang, then navigator.languages, then en', () => {
    setNavigatorLanguages(['zh-TW', 'en-US'])
    expect(detectLanguage()).toBe('zh')
    localStorage.setItem('tp_lang', 'bn')
    expect(detectLanguage()).toBe('bn')
    localStorage.setItem('tp_lang', 'xx')
    setNavigatorLanguages(['pt-BR', 'ja'])
    expect(detectLanguage()).toBe('en')
  })

  it('survives storage that throws (private mode)', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('denied') })
    setNavigatorLanguages(['fr-CA'])
    expect(detectLanguage()).toBe('fr')
  })
})

describe('setLanguage', () => {
  it('persists, sets <html lang> and loads the script font once', async () => {
    await setLanguage('hi')
    expect(i18n.language).toBe('hi')
    expect(localStorage.getItem('tp_lang')).toBe('hi')
    expect(document.documentElement.lang).toBe('hi-IN')
    await setLanguage('en')
    await setLanguage('hi')
    const links = [...document.head.querySelectorAll('link[href*="fonts.googleapis.com"]')]
    expect(links).toHaveLength(1)
    expect(links[0].href).toContain('Noto+Sans+Devanagari')
    expect(i18n.t('common:nav.search')).toBe('खोजें')
  })

  it('ignores unsupported codes', async () => {
    await setLanguage('xx')
    expect(i18n.language).toBe('en')
  })

  it('bundles every en namespace', () => {
    expect(NAMESPACES).toContain('common')
    expect(i18n.hasResourceBundle('en', 'common')).toBe(true)
  })
})

describe('lazy English namespaces', () => {
  it('keeps NAMESPACES unchanged: every en file, sorted', () => {
    const files = Object.keys(import.meta.glob('./locales/en/*.json'))
      .map((p) => p.split('/').pop().replace(/\.json$/, '')).sort()
    expect(NAMESPACES).toEqual(files)
  })

  it('bundles the eager core and leaves the lazy namespaces out of the main bundle', () => {
    for (const ns of ['common', 'errors', 'auth', 'journey', 'misc']) expect(BUNDLED_NAMESPACES).toContain(ns)
    for (const ns of ['accountData', 'accountSettings', 'adminInvites', 'adminTelemetry', 'security', 'mobile']) {
      expect(NAMESPACES).toContain(ns)
      expect(BUNDLED_NAMESPACES).not.toContain(ns)
    }
  })

  it('has every namespace loaded in tests (bundleAll)', () => {
    for (const ns of NAMESPACES) expect(i18n.hasResourceBundle('en', ns), ns).toBe(true)
    expect(i18n.t('accountData:export.button')).toBe('Download my data')
  })
})

describe('namespace exports', () => {
  it('are frozen and unchanged by loading another namespace', async () => {
    const before = [[...NAMESPACES], [...BUNDLED_NAMESPACES]]
    expect(Object.isFrozen(NAMESPACES)).toBe(true)
    expect(Object.isFrozen(BUNDLED_NAMESPACES)).toBe(true)
    await i18n.loadNamespaces(['notAFile', 'accountData'])
    expect([[...NAMESPACES], [...BUNDLED_NAMESPACES]]).toEqual(before)
    expect(NAMESPACES).not.toContain('notAFile')
  })
})

describe('prefetchLazyNamespaces', () => {
  it('loads the routed lazy namespaces once the browser is idle', async () => {
    const idle = vi.fn((cb) => { cb(); return 1 })
    vi.stubGlobal('requestIdleCallback', idle)
    const load = vi.spyOn(i18n, 'loadNamespaces').mockResolvedValue()
    prefetchLazyNamespaces()
    expect(idle).toHaveBeenCalledTimes(1)
    const [list] = load.mock.calls[0]
    expect(list).toEqual(expect.arrayContaining(['accountData', 'accountSettings', 'security', 'adminInvites', 'adminTelemetry']))
    expect(list).not.toContain('mobile')
    for (const ns of list) expect(NAMESPACES).toContain(ns)
    vi.unstubAllGlobals()
  })

  it('falls back to setTimeout and never throws', async () => {
    vi.stubGlobal('requestIdleCallback', undefined)
    vi.useFakeTimers()
    const load = vi.spyOn(i18n, 'loadNamespaces').mockRejectedValue(new Error('offline'))
    expect(() => prefetchLazyNamespaces()).not.toThrow()
    expect(load).not.toHaveBeenCalled()
    await vi.runAllTimersAsync()
    expect(load).toHaveBeenCalledTimes(1)
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })
})
