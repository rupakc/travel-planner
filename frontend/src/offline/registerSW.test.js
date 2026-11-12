import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { ensureServiceWorker, precacheShell, disableOffline } from './registerSW'
import { savePack, listPacks } from './packStore'
import { _resetForTests } from './idb'

let originalSW
const hadSW = 'serviceWorker' in navigator

function installSW(sw) {
  Object.defineProperty(navigator, 'serviceWorker', { value: sw, configurable: true })
}

beforeEach(() => {
  _resetForTests()
  originalSW = navigator.serviceWorker
  vi.stubEnv('DEV', false)
  Object.defineProperty(window, 'isSecureContext', { value: true, configurable: true })
})

afterEach(() => {
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
  if (hadSW) installSW(originalSW)
  else delete navigator.serviceWorker
})

describe('ensureServiceWorker', () => {
  it('returns null (unsupported) without navigator.serviceWorker', async () => {
    delete navigator.serviceWorker
    expect(await ensureServiceWorker()).toBeNull()
  })

  it('returns null and never registers when /config says offline_pack is false', async () => {
    const register = vi.fn()
    installSW({ register })
    vi.resetModules()
    vi.doMock('../hooks/useClientConfig', () => ({ loadClientConfig: async () => ({ features: { offline_pack: false } }) }))
    const mod = await import('./registerSW')
    expect(await mod.ensureServiceWorker()).toBeNull()
    expect(register).not.toHaveBeenCalled()
    vi.doUnmock('../hooks/useClientConfig')
  })

  it('returns null outside a secure context', async () => {
    const register = vi.fn()
    installSW({ register })
    Object.defineProperty(window, 'isSecureContext', { value: false, configurable: true })
    expect(await ensureServiceWorker()).toBeNull()
    expect(register).not.toHaveBeenCalled()
  })

  it('returns null in the dev server', async () => {
    vi.stubEnv('DEV', true)
    const register = vi.fn()
    installSW({ register })
    expect(await ensureServiceWorker()).toBeNull()
    expect(register).not.toHaveBeenCalled()
  })

  it('registers /sw.js at the root scope', async () => {
    const reg = { scope: '/' }
    const register = vi.fn().mockResolvedValue(reg)
    installSW({ register })
    expect(await ensureServiceWorker()).toBe(reg)
    expect(register).toHaveBeenCalledWith('/sw.js', { scope: '/' })
  })

  it('a failed registration resolves null', async () => {
    installSW({ register: vi.fn().mockRejectedValue(new Error('SecurityError')) })
    expect(await ensureServiceWorker()).toBeNull()
  })
})

describe('precacheShell', () => {
  it('asks the active worker to precache and reports kB', async () => {
    const active = {
      postMessage: vi.fn((msg, [port]) => {
        expect(msg).toEqual({ type: 'precache' })
        port.postMessage({ ok: true, bytes: 5 * 1024 })
      }),
    }
    const reg = { active }
    installSW({ getRegistration: vi.fn().mockResolvedValue(reg), ready: Promise.resolve(reg) })
    expect(await precacheShell()).toEqual({ ok: true, kb: 5 })
  })

  it('without a registration it answers ok: false', async () => {
    installSW({ getRegistration: vi.fn().mockResolvedValue(undefined), ready: new Promise(() => {}) })
    expect(await precacheShell()).toEqual({ ok: false, kb: 0 })
  })
})

describe('disableOffline', () => {
  it('purges the voyager caches, unregisters /sw.js and deletes every pack', async () => {
    const names = new Set(['voyager-shell-1', 'other'])
    vi.stubGlobal('caches', {
      keys: async () => [...names],
      delete: async (n) => names.delete(n),
    })
    const ours = { active: { scriptURL: 'https://v.test/sw.js', postMessage: vi.fn() }, unregister: vi.fn().mockResolvedValue(true) }
    const theirs = { active: { scriptURL: 'https://v.test/other-sw.js', postMessage: vi.fn() }, unregister: vi.fn() }
    installSW({ getRegistrations: vi.fn().mockResolvedValue([ours, theirs]) })
    await savePack(1, { trip_id: 1 })
    await savePack(2, { trip_id: 2 })
    await disableOffline()
    expect([...names]).toEqual(['other'])
    expect(ours.unregister).toHaveBeenCalled()
    expect(ours.active.postMessage).toHaveBeenCalledWith({ type: 'purge' })
    expect(theirs.unregister).not.toHaveBeenCalled()
    expect(await listPacks(1)).toEqual([])
    expect(await listPacks(2)).toEqual([])
  })

  it('is safe where nothing is supported', async () => {
    delete navigator.serviceWorker
    await expect(disableOffline()).resolves.toBeUndefined()
  })
})
