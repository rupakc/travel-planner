// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'

const emit = vi.hoisted(() => vi.fn())
vi.mock('../telemetry/client', () => ({ emit }))

globalThis.IS_REACT_ACT_ENVIRONMENT = true
let container, root

async function render(features, override) {
  vi.resetModules()
  if (override === undefined) localStorage.removeItem('tp_journey')
  else localStorage.setItem('tp_journey', override)
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
    features === null ? { ok: false, status: 404 } : { ok: true, json: async () => ({ features }) }))
  const { useJourney } = await import('./useJourney')
  const seen = []
  function Probe() { seen.push(useJourney()); return null }
  container = document.createElement('div')
  root = createRoot(container)
  await act(async () => root.render(createElement(Probe)))
  await act(async () => { await new Promise((r) => setTimeout(r, 0)) })
  return seen
}

beforeEach(() => { emit.mockClear() })
afterEach(() => { act(() => root.unmount()); localStorage.clear(); vi.unstubAllGlobals() })

describe('useJourney', () => {
  it('old backend keeps the classic shell: no features.trips, even with tp_journey=1', async () => {
    const seen = await render({ accounts: true }, '1')
    expect(seen.at(-1)).toEqual({ enabled: false, tripsApi: false, offlinePack: false, loaded: true })
  })

  it('a 404 /config keeps the classic shell', async () => {
    const seen = await render(null, '1')
    expect(seen.at(-1)).toMatchObject({ enabled: false, tripsApi: false, loaded: true })
  })

  it('is off before /config answers', async () => {
    const seen = await render({ trips: true, journey: true })
    expect(seen[0]).toEqual({ enabled: false, tripsApi: false, offlinePack: false, loaded: false })
  })

  it('features.journey true → enabled', async () => {
    const seen = await render({ trips: true, journey: true, offline_pack: true })
    expect(seen.at(-1)).toEqual({ enabled: true, tripsApi: true, offlinePack: true, loaded: true })
    await vi.waitFor(() => expect(emit).toHaveBeenCalledWith('journey_shell', { enabled: true, source: 'config' }))
  })

  it('tp_journey=1 turns it on for this browser when the trips API exists', async () => {
    const seen = await render({ trips: true, journey: false, offline_pack: false }, '1')
    expect(seen.at(-1)).toEqual({ enabled: true, tripsApi: true, offlinePack: false, loaded: true })
    await vi.waitFor(() => expect(emit).toHaveBeenCalledWith('journey_shell', { enabled: true, source: 'override' }))
  })

  it('tp_journey=0 → off, even when the server enables it', async () => {
    const seen = await render({ trips: true, journey: true }, '0')
    expect(seen.at(-1)).toMatchObject({ enabled: false, tripsApi: true, loaded: true })
    await vi.waitFor(() => expect(emit).toHaveBeenCalledWith('journey_shell', { enabled: false, source: 'off' }))
  })

  it('emits journey_shell once per page load', async () => {
    await render({ trips: true, journey: true })
    const { useJourney } = await import('./useJourney')
    function Probe() { useJourney(); return null }
    const second = createRoot(document.createElement('div'))
    await act(async () => second.render(createElement(Probe)))
    act(() => second.unmount())
    await vi.waitFor(() => expect(emit).toHaveBeenCalled())
    expect(emit.mock.calls.filter(([e]) => e === 'journey_shell')).toHaveLength(1)
  })
})
