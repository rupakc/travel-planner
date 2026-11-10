// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'

// Consent depends on the machine's timezone; the tests control it directly.
const consent = vi.hoisted(() => ({ allowed: true }))
vi.mock('./consent', () => ({
  telemetryAllowed: () => consent.allowed,
  consentRequired: () => false,
  getConsent: () => null,
  setConsent: () => {},
}))

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/
const ID = /^[A-Za-z0-9_.:/-]{1,64}$/
const CONFIG = { telemetry: { enabled: true, flush_interval_s: 15, max_batch: 50 } }

const res = (status, body, hdrs = {}) => ({
  ok: status >= 200 && status < 300,
  status,
  json: async () => body,
  headers: { get: (k) => hdrs[k.toLowerCase()] ?? null },
})

let c, fetchMock, telemetryReply
const telemetryCalls = () => fetchMock.mock.calls.filter(([u]) => u === '/api/telemetry')
const lastBody = () => JSON.parse(telemetryCalls().at(-1)[1].body)

async function load({ config = res(200, CONFIG) } = {}) {
  fetchMock = vi.fn(async (url) => {
    if (url === '/api/config') return typeof config === 'function' ? config() : config
    return telemetryReply()
  })
  globalThis.fetch = fetchMock
  vi.resetModules()
  c = await import('./client')
  return c
}

beforeEach(() => {
  vi.useFakeTimers()
  consent.allowed = true
  telemetryReply = async () => res(204)
  try { localStorage.clear(); sessionStorage.clear() } catch { /* ignore */ }
  window.history.pushState({}, '', '/')
})

afterEach(() => {
  try { c?._resetForTests() } catch { /* ignore */ }
  vi.useRealTimers()
  vi.restoreAllMocks()
  delete navigator.sendBeacon
})

describe('emit + flush', () => {
  it('sends a well-formed batch that passes the server rules', async () => {
    await load()
    window.history.pushState({}, '', '/share/tok-123')
    c.initTelemetry({ appVersion: '1.2.3' })
    c.emit('feature_used', { feature: 'plan_saved', page: 'results' })
    await c.flush()
    const body = lastBody()
    expect(body.client.platform).toBe('web')
    expect(body.client.app_version).toBe('1.2.3')
    expect(body.client.anon_id).toMatch(UUID)
    expect(body.client.session_id).toMatch(UUID)
    expect(body.client.locale).toMatch(ID)
    const ev = body.events.find((e) => e.event === 'feature_used')
    expect(ev.props).toEqual({ feature: 'plan_saved', page: 'results' })
    expect(ev.screen).toBe('/share/:token')
    expect(typeof ev.ts).toBe('number')
    expect(JSON.stringify(body)).not.toContain('tok-123')
    expect(body.events.map((e) => e.event)).toEqual(expect.arrayContaining(['app_open', 'session_start']))
  })

  it('sanitises app_version to the server id rule (the default build value has a "+")', async () => {
    await load()
    c.initTelemetry({ appVersion: '0.0.0+20261110' })
    c.emit('app_background')
    await c.flush()
    expect(lastBody().client.app_version).toBe('0.0.0_20261110')
    expect(lastBody().client.app_version).toMatch(ID)
  })

  it('keeps the anon id in tp_anon across loads', async () => {
    await load()
    c.initTelemetry({ appVersion: '1' })
    c.emit('app_background')
    await c.flush()
    const first = lastBody().client.anon_id
    expect(localStorage.getItem('tp_anon')).toBe(first)
    c._resetForTests()
    await load()
    c.initTelemetry({ appVersion: '1' })
    c.emit('app_background')
    await c.flush()
    expect(lastBody().client.anon_id).toBe(first)
  })

  it('attaches the bearer token when signed in, not otherwise', async () => {
    await load()
    c.initTelemetry({ appVersion: '1' })
    c.emit('app_background')
    await c.flush()
    expect(telemetryCalls()[0][1].headers.Authorization).toBeUndefined()
    localStorage.setItem('tp_token', 'abc')
    c.emit('app_background')
    await c.flush()
    expect(telemetryCalls()[1][1].headers.Authorization).toBe('Bearer abc')
    c.setUserPresent(false)
    c.emit('app_background')
    await c.flush()
    expect(telemetryCalls()[2][1].headers.Authorization).toBeUndefined()
  })

  it('buffers events emitted before init and sends them once enabled', async () => {
    await load()
    c.emit('screen_view', { route: '/' })
    c.initTelemetry({ appVersion: '1' })
    await c.flush()
    expect(lastBody().events.map((e) => e.event)).toContain('screen_view')
  })

  it('flushes on the interval and at max_batch', async () => {
    await load({ config: res(200, { telemetry: { enabled: true, flush_interval_s: 15, max_batch: 5 } }) })
    c.initTelemetry({ appVersion: '1' })
    await vi.advanceTimersByTimeAsync(0)
    await vi.advanceTimersByTimeAsync(15_010) // + the idle-time hop
    expect(telemetryCalls().length).toBe(1) // app_open + session_start on the interval
    for (let i = 0; i < 5; i++) c.emit('app_background')
    await vi.advanceTimersByTimeAsync(10)
    expect(telemetryCalls().length).toBe(2)
    expect(lastBody().events.length).toBe(5)
  })

  it('never sends more than max_batch events in one request', async () => {
    await load({ config: res(200, { telemetry: { enabled: true, flush_interval_s: 15, max_batch: 3 } }) })
    c.initTelemetry({ appVersion: '1' })
    for (let i = 0; i < 7; i++) c.emit('app_background')
    await c.flush()
    for (const [, opts] of telemetryCalls()) expect(JSON.parse(opts.body).events.length).toBeLessThanOrEqual(3)
  })
})

describe('hostile environments', () => {
  it('with localStorage throwing, emit does not throw and events stay in memory', async () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('denied') })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('denied') })
    vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => { throw new Error('denied') })
    await load()
    expect(() => c.initTelemetry({ appVersion: '1' })).not.toThrow()
    expect(() => c.emit('ui_tap', { tid: 'search.submit', route: '/' })).not.toThrow()
    expect(c._queueForTests().some((e) => e.event === 'ui_tap')).toBe(true)
    await c.flush()
    expect(lastBody().events.map((e) => e.event)).toContain('ui_tap')
    expect(lastBody().client.anon_id).toMatch(UUID)
  })

  it('works when crypto.randomUUID is unavailable', async () => {
    vi.spyOn(globalThis.crypto, 'randomUUID').mockImplementation(() => { throw new Error('insecure context') })
    await load()
    c.initTelemetry({ appVersion: '1' })
    c.emit('app_background')
    await c.flush()
    expect(lastBody().client.anon_id).toMatch(UUID)
  })

  it('backs off after 3 consecutive network failures: no 4th immediate call', async () => {
    telemetryReply = async () => { throw new TypeError('Failed to fetch') }
    await load()
    c.initTelemetry({ appVersion: '1' })
    c.emit('app_background')
    await c.flush()
    await c.flush()
    await c.flush()
    expect(telemetryCalls().length).toBe(3)
    await c.flush()
    c.emit('app_background')
    await vi.advanceTimersByTimeAsync(20_000)
    expect(telemetryCalls().length).toBe(3)
    // events are kept for later, and the SDK recovers once the network does
    expect(c._queueForTests().length).toBeGreaterThan(0)
    telemetryReply = async () => res(204)
    await vi.advanceTimersByTimeAsync(5 * 60_000)
    expect(telemetryCalls().length).toBe(4)
    expect(c._queueForTests().length).toBe(0)
  })

  it('caps the backoff at 5 minutes', async () => {
    telemetryReply = async () => { throw new TypeError('Failed to fetch') }
    await load()
    c.initTelemetry({ appVersion: '1' })
    c.emit('app_background')
    for (let i = 0; i < 3; i++) await c.flush()
    await vi.advanceTimersByTimeAsync(60 * 60_000)
    const n = telemetryCalls().length
    await vi.advanceTimersByTimeAsync(5 * 60_000 + 1_000)
    expect(telemetryCalls().length).toBe(n + 1)
  })

  it('the first POST 404 disables it: later emits make no network calls', async () => {
    telemetryReply = async () => res(404)
    await load()
    c.initTelemetry({ appVersion: '1' })
    c.emit('app_background')
    await c.flush()
    expect(telemetryCalls().length).toBe(1)
    const before = fetchMock.mock.calls.length
    c.emit('app_background')
    c.emit('ui_tap', { tid: 'x', route: '/' })
    await c.flush()
    await vi.advanceTimersByTimeAsync(10 * 60_000)
    document.dispatchEvent(new Event('visibilitychange'))
    expect(fetchMock.mock.calls.length).toBe(before)
    expect(c._queueForTests().length).toBe(0)
  })

  it('/api/config 404 (old backend) turns it off without retries', async () => {
    await load({ config: res(404) })
    c.initTelemetry({ appVersion: '1' })
    c.emit('app_background')
    await c.flush()
    await vi.advanceTimersByTimeAsync(10 * 60_000)
    expect(telemetryCalls().length).toBe(0)
    expect(fetchMock.mock.calls.filter(([u]) => u === '/api/config').length).toBe(1)
  })

  it('/api/config network failure turns it off too', async () => {
    await load({ config: () => Promise.reject(new TypeError('offline')) })
    c.initTelemetry({ appVersion: '1' })
    c.emit('app_background')
    await c.flush()
    expect(telemetryCalls().length).toBe(0)
  })

  it('enabled:false turns it off', async () => {
    await load({ config: res(200, { telemetry: { enabled: false } }) })
    c.initTelemetry({ appVersion: '1' })
    c.emit('app_background')
    await c.flush()
    expect(telemetryCalls().length).toBe(0)
  })

  it('fetches /api/config only once even if init is called twice', async () => {
    await load()
    c.initTelemetry({ appVersion: '1' })
    c.initTelemetry({ appVersion: '1' })
    await c.flush()
    expect(fetchMock.mock.calls.filter(([u]) => u === '/api/config').length).toBe(1)
  })

  it('drops a rejected batch (422) instead of retrying it', async () => {
    telemetryReply = async () => res(422)
    await load()
    c.initTelemetry({ appVersion: '1' })
    await c.flush()
    expect(telemetryCalls().length).toBe(1)
    expect(c._queueForTests().length).toBe(0)
    await c.flush()
    expect(telemetryCalls().length).toBe(1)
  })

  it('emit never throws on bad input', async () => {
    await load()
    c.initTelemetry({ appVersion: '1' })
    expect(() => c.emit()).not.toThrow()
    expect(() => c.emit(42, 'x')).not.toThrow()
    expect(() => c.emit('ui_tap', { cyclic: (() => { const o = {}; o.o = o; return o })() })).not.toThrow()
    await c.flush()
  })
})

describe('consent', () => {
  it('drops events while telemetry is not allowed', async () => {
    consent.allowed = false
    await load()
    c.initTelemetry({ appVersion: '1' })
    c.emit('app_background')
    await c.flush()
    expect(telemetryCalls().length).toBe(0)
    expect(c._queueForTests().length).toBe(0)
  })

  it('a denial sends nothing at all and clears what was queued', async () => {
    await load()
    c.initTelemetry({ appVersion: '1' })
    await vi.advanceTimersByTimeAsync(0)
    c.emit('app_background')
    consent.allowed = false
    c.emit('consent', { choice: 'denied' })
    await c.flush()
    await vi.advanceTimersByTimeAsync(10 * 60_000)
    expect(telemetryCalls().length).toBe(0)
    expect(c._queueForTests().length).toBe(0)
  })

  it('a later grant restores the persisted queue and emits app_open, like init', async () => {
    localStorage.setItem('tp_tq', JSON.stringify([
      { event: 'screen_view', ts: Date.now() - 1000, props: { route: '/chat' }, screen: '/chat', sid: '6f1c1d36-8a43-4d1a-9c55-0f7a1f6a7e11' },
    ]))
    consent.allowed = false
    await load()
    c.initTelemetry({ appVersion: '1' })
    await c.flush()
    expect(telemetryCalls().length).toBe(0)
    consent.allowed = true
    c.emit('consent', { choice: 'granted' })
    await c.flush()
    const evs = telemetryCalls().flatMap(([, o]) => JSON.parse(o.body).events).map((e) => e.event)
    expect(evs).toEqual(expect.arrayContaining(['consent', 'app_open', 'screen_view']))
  })
})

describe('consent before init', () => {
  it('a denial recorded before /api/config answers sends nothing', async () => {
    await load()
    c.emit('app_background')
    consent.allowed = false
    c.emit('consent', { choice: 'denied' })
    c.initTelemetry({ appVersion: '1' })
    await c.flush()
    expect(telemetryCalls().length).toBe(0)
  })
})

describe('persistence', () => {
  it('persists the queue to tp_tq, capped at 500 (oldest dropped)', async () => {
    telemetryReply = async () => { throw new TypeError('offline') }
    await load()
    c.initTelemetry({ appVersion: '1' })
    await vi.advanceTimersByTimeAsync(0)
    for (let i = 0; i < 520; i++) c.emit('screen_time', { route: '/', ms: i })
    document.dispatchEvent(new Event('visibilitychange'))
    Object.defineProperty(document, 'visibilityState', { value: 'hidden', configurable: true })
    document.dispatchEvent(new Event('visibilitychange'))
    Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true })
    await vi.advanceTimersByTimeAsync(10)
    const saved = JSON.parse(localStorage.getItem('tp_tq'))
    expect(saved.length).toBe(500)
    expect(saved.some((e) => e.props?.ms === 0)).toBe(false)
    expect(saved.some((e) => e.props?.ms === 519)).toBe(true)
  })

  it('sends events persisted by an earlier page load', async () => {
    localStorage.setItem('tp_tq', JSON.stringify([
      { event: 'screen_view', ts: Date.now() - 1000, props: { route: '/chat' }, screen: '/chat', sid: '6f1c1d36-8a43-4d1a-9c55-0f7a1f6a7e11' },
    ]))
    await load()
    c.initTelemetry({ appVersion: '1' })
    await c.flush()
    const all = telemetryCalls().flatMap(([, o]) => JSON.parse(o.body).events)
    expect(all.some((e) => e.event === 'screen_view' && e.props.route === '/chat')).toBe(true)
  })
})

describe('page hidden', () => {
  const hide = () => {
    Object.defineProperty(document, 'visibilityState', { value: 'hidden', configurable: true })
    document.dispatchEvent(new Event('visibilitychange'))
    Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true })
    document.dispatchEvent(new Event('visibilitychange'))
  }
  const blobText = (blob) => new Promise((resolve) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result)
    reader.readAsText(blob)
  })

  it('anonymous: uses sendBeacon with an application/json Blob', async () => {
    navigator.sendBeacon = vi.fn(() => true)
    await load()
    c.initTelemetry({ appVersion: '1' })
    await vi.advanceTimersByTimeAsync(0)
    c.emit('ui_tap', { tid: 'x', route: '/' })
    hide()
    expect(navigator.sendBeacon).toHaveBeenCalled()
    const [url, blob] = navigator.sendBeacon.mock.calls[0]
    expect(url).toBe('/api/telemetry')
    expect(blob).toBeInstanceOf(Blob)
    expect(blob.type).toBe('application/json')
    vi.useRealTimers() // jsdom's FileReader runs on timers
    const body = JSON.parse(await blobText(blob))
    expect(body.events.map((e) => e.event)).toEqual(expect.arrayContaining(['ui_tap', 'app_background']))
    expect(telemetryCalls().length).toBe(0)
  })

  it('signed in: fetch with keepalive + auth first, beacon as fallback', async () => {
    navigator.sendBeacon = vi.fn(() => true)
    localStorage.setItem('tp_token', 'tok')
    await load()
    c.initTelemetry({ appVersion: '1' })
    await vi.advanceTimersByTimeAsync(0)
    c.emit('ui_tap', { tid: 'x', route: '/' })
    hide()
    const [, opts] = telemetryCalls().at(-1)
    expect(opts.keepalive).toBe(true)
    expect(opts.headers.Authorization).toBe('Bearer tok')
    expect(navigator.sendBeacon).not.toHaveBeenCalled()

    telemetryReply = async () => { throw new TypeError('aborted') }
    c.emit('ui_tap', { tid: 'y', route: '/' })
    hide()
    await vi.advanceTimersByTimeAsync(0)
    expect(navigator.sendBeacon).toHaveBeenCalled()
  })
})

describe('sessions and screens', () => {
  it('rotates session_id after 30 minutes idle', async () => {
    await load()
    c.initTelemetry({ appVersion: '1' })
    c.emit('app_background')
    await c.flush()
    const s1 = lastBody().client.session_id
    vi.setSystemTime(Date.now() + 31 * 60_000)
    c.emit('app_background')
    await c.flush()
    const body = lastBody()
    expect(body.client.session_id).not.toBe(s1)
    expect(body.client.session_id).toMatch(UUID)
    expect(body.events.map((e) => e.event)).toContain('session_start')
  })

  it('screenView emits screen_view with referrer and screen_time for the previous route', async () => {
    await load()
    c.initTelemetry({ appVersion: '1' })
    c.screenView('/')
    vi.advanceTimersByTime(2_000)
    c.screenView('/share/abc')
    await c.flush()
    const evs = telemetryCalls().flatMap(([, o]) => JSON.parse(o.body).events)
    expect(evs).toEqual(expect.arrayContaining([
      expect.objectContaining({ event: 'screen_view', props: { route: '/' } }),
      expect.objectContaining({ event: 'screen_view', props: { route: '/share/:token', referrer_route: '/' } }),
      expect.objectContaining({ event: 'screen_time', props: { route: '/', ms: 2000 } }),
    ]))
  })
})

describe('utils/analytics track()', () => {
  it('keeps posting to /api/analytics/events and also emits feature_used', async () => {
    localStorage.setItem('tp_token', 'tok')
    await load()
    const { track } = await import('../utils/analytics')
    c.initTelemetry({ appVersion: '1' })
    track('plan_saved', 'results', { is_update: true })
    await vi.advanceTimersByTimeAsync(5_000)
    const legacy = fetchMock.mock.calls.filter(([u]) => u === '/api/analytics/events')
    expect(legacy.length).toBe(1)
    expect(JSON.parse(legacy[0][1].body).events[0]).toMatchObject({ feature: 'plan_saved', page: 'results', metadata: { is_update: true } })
    await c.flush()
    const evs = telemetryCalls().flatMap(([, o]) => JSON.parse(o.body).events)
    expect(evs).toEqual(expect.arrayContaining([
      expect.objectContaining({ event: 'feature_used', props: { feature: 'plan_saved', page: 'results' } }),
    ]))
  })
})

describe('429 Retry-After', () => {
  it('honours Retry-After in seconds', async () => {
    telemetryReply = async () => res(429, null, { 'retry-after': '120' })
    await load()
    c.initTelemetry({ appVersion: '1' })
    await c.flush()
    expect(telemetryCalls().length).toBe(1)
    telemetryReply = async () => res(204)
    await c.flush()
    await vi.advanceTimersByTimeAsync(100_000)
    expect(telemetryCalls().length).toBe(1)
    await vi.advanceTimersByTimeAsync(25_000)
    expect(telemetryCalls().length).toBe(2)
  })

  it('honours Retry-After as an HTTP date', async () => {
    telemetryReply = async () => res(429, null, { 'retry-after': new Date(Date.now() + 90_000).toUTCString() })
    await load()
    c.initTelemetry({ appVersion: '1' })
    await c.flush()
    telemetryReply = async () => res(204)
    await vi.advanceTimersByTimeAsync(80_000)
    expect(telemetryCalls().length).toBe(1)
    await vi.advanceTimersByTimeAsync(20_000)
    expect(telemetryCalls().length).toBe(2)
  })
})

describe('no duplicate sends on hide', () => {
  const setVisibility = (v) => {
    Object.defineProperty(document, 'visibilityState', { value: v, configurable: true })
    document.dispatchEvent(new Event('visibilitychange'))
  }
  afterEach(() => {
    Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true })
  })

  it('signed-in hide flush: keepalive events are in flight, not persisted, not re-sent', async () => {
    localStorage.setItem('tp_token', 'tok')
    await load()
    c.initTelemetry({ appVersion: '1' })
    await vi.advanceTimersByTimeAsync(0)
    c.emit('ui_tap', { tid: 'sent.on.hide', route: '/' })
    telemetryReply = () => new Promise(() => {}) // the page unloads mid round trip
    setVisibility('hidden')
    expect(telemetryCalls().length).toBe(1)
    expect(telemetryCalls()[0][1].keepalive).toBe(true)
    // a timer or drain during the round trip does not send them again
    await c.flush()
    await vi.advanceTimersByTimeAsync(60_000)
    expect(telemetryCalls().length).toBe(1)
    // simulated unload, then the next page load
    const saved = localStorage.getItem('tp_tq')
    expect(saved === null || !saved.includes('sent.on.hide')).toBe(true)
    c._resetForTests()
    if (saved !== null) localStorage.setItem('tp_tq', saved)
    Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true })
    telemetryReply = async () => res(204)
    await load()
    c.initTelemetry({ appVersion: '1' })
    await c.flush()
    const resent = telemetryCalls().flatMap(([, o]) => JSON.parse(o.body).events)
    expect(resent.some((e) => e.props?.tid === 'sent.on.hide')).toBe(false)
  })
})

describe('auto-captured ui_change through the client', () => {
  it('a text input change is sent as ui_change with tid + route only', async () => {
    await load()
    c.initTelemetry({ appVersion: '1' })
    await vi.advanceTimersByTimeAsync(0)
    document.body.innerHTML = '<input data-tid="search.dest">'
    const input = document.querySelector('input')
    input.value = 'Paris jane@x.com'
    input.dispatchEvent(new Event('change', { bubbles: true }))
    await c.flush()
    const body = lastBody()
    expect(body.events).toEqual(expect.arrayContaining([
      expect.objectContaining({ event: 'ui_change', props: { tid: 'search.dest', route: '/' } }),
    ]))
    expect(JSON.stringify(body)).not.toMatch(/Paris|jane/)
    document.body.innerHTML = ''
  })
})
