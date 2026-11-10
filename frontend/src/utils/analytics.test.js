// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'

vi.mock('../telemetry/client', () => ({ emit: vi.fn() }))

import { _resetConsentForTests, setConsent } from '../telemetry/consent'
import { track } from './analytics'

const zone = (tz) => vi.spyOn(Intl.DateTimeFormat.prototype, 'resolvedOptions')
  .mockReturnValue({ timeZone: tz, locale: 'en' })
const posts = () => globalThis.fetch.mock.calls.filter(([url]) => url === '/api/analytics/events')

beforeEach(() => {
  // only the timers: faking Intl too would defeat the time-zone spy
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
  globalThis.fetch = vi.fn(() => Promise.resolve({ ok: true }))
  localStorage.setItem('tp_token', 'tok')
})
afterEach(() => {
  vi.runOnlyPendingTimers()
  vi.useRealTimers()
  vi.restoreAllMocks()
  localStorage.clear()
  _resetConsentForTests()
})

describe('legacy feature analytics respects the telemetry switch', () => {
  it('sends when telemetry is allowed', () => {
    zone('America/New_York')
    track('search', 'search')
    vi.advanceTimersByTime(6000)
    expect(posts()).toHaveLength(1)
  })

  it('sends nothing after "No thanks"', () => {
    zone('America/New_York')
    setConsent('denied')
    for (let i = 0; i < 12; i++) track('search', 'search', { n: i })
    vi.advanceTimersByTime(6000)
    expect(posts()).toHaveLength(0)
  })

  it('sends nothing in an EU timezone before a choice', () => {
    zone('Europe/Paris')
    track('search', 'search')
    vi.advanceTimersByTime(6000)
    expect(posts()).toHaveLength(0)
  })

  it('drops events queued before an opt-out', () => {
    zone('America/New_York')
    track('search', 'search')
    setConsent('denied')
    vi.advanceTimersByTime(6000)
    expect(posts()).toHaveLength(0)
  })
})
