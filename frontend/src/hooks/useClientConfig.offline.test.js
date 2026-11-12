// @vitest-environment jsdom
// The last good /config (tp_config_cache) is used when /config gets no answer.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'

vi.mock('../telemetry/client', () => ({ emit: vi.fn() }))

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const ON = { features: { trips: true, journey: true, offline_pack: true } }
const answer = (body) => ({ ok: true, status: 200, json: async () => body })

async function freshConfig(fetchImpl) {
  vi.resetModules()
  vi.stubGlobal('fetch', fetchImpl)
  return import('./useClientConfig')
}

beforeEach(() => { localStorage.clear() })
afterEach(() => { vi.unstubAllGlobals(); localStorage.clear() })

describe('useClientConfig offline', () => {
  it('keeps the journey on offline from the cached config', async () => {
    // online load stores the answer
    let m = await freshConfig(vi.fn().mockResolvedValue(answer(ON)))
    expect(await m.loadClientConfig()).toEqual(ON)
    expect(JSON.parse(localStorage.getItem('tp_config_cache'))).toEqual(ON)

    // reload in airplane mode: /config never answers
    vi.resetModules()
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    const { useJourney } = await import('./useJourney')
    const seen = []
    function Probe() { seen.push(useJourney()); return null }
    const root = createRoot(document.createElement('div'))
    await act(async () => root.render(createElement(Probe)))
    await act(async () => { await new Promise((r) => setTimeout(r, 0)) })
    expect(seen.at(-1)).toEqual({ enabled: true, tripsApi: true, offlinePack: true, loaded: true })
    act(() => root.unmount())
  })

  it('a fresh answer wins over the cache (offline_pack false)', async () => {
    localStorage.setItem('tp_config_cache', JSON.stringify(ON))
    const off = { features: { trips: true, journey: true, offline_pack: false } }
    const m = await freshConfig(vi.fn().mockResolvedValue(answer(off)))
    expect((await m.loadClientConfig()).features.offline_pack).toBe(false)
    expect(JSON.parse(localStorage.getItem('tp_config_cache')).features.offline_pack).toBe(false)
  })

  it('an HTTP error behaves as today ({}) and forgets the cache', async () => {
    localStorage.setItem('tp_config_cache', JSON.stringify(ON))
    const m = await freshConfig(vi.fn().mockResolvedValue({ ok: false, status: 404 }))
    expect(await m.loadClientConfig()).toEqual({})
    expect(localStorage.getItem('tp_config_cache')).toBeNull()
  })

  it('no answer and no cache gives {}', async () => {
    const m = await freshConfig(vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    expect(await m.loadClientConfig()).toEqual({})
  })

  it('a corrupt cache is ignored', async () => {
    localStorage.setItem('tp_config_cache', '{not json')
    const m = await freshConfig(vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    expect(await m.loadClientConfig()).toEqual({})
  })
})
