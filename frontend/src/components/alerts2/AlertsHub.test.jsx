// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'

const state = { live: true, hide: false, me: null }
vi.mock('../../context/AuthContext', () => ({ useAuth: () => ({ token: 'tok' }) }))
vi.mock('../../hooks/useAlertsV2', () => ({ useAlertsV2: () => ({ on: true, livePrices: state.live }) }))
vi.mock('../account/SettingsSync', () => ({ useAccountSettings: () => ({ settings: { hide_game: state.hide } }) }))
vi.mock('../game/useGameMe', () => ({ default: () => ({ me: state.me }) }))
vi.mock('../../services/gameApi', () => ({ getGameCatalog: vi.fn() }))
vi.mock('../../services/alertsApi', () => ({
  getSavings: vi.fn(), getStory: vi.fn(), requestAdvice: vi.fn(), getAlertPrefs: vi.fn(), putAlertPrefs: vi.fn(),
}))
vi.mock('../../services/api', () => ({ updateFareWatch: vi.fn(), updatePriceWatch: vi.fn() }))
vi.mock('../../services/accountApi', () => ({ patchSettings: vi.fn() }))
vi.mock('../../telemetry/client', () => ({ emit: vi.fn() }))

import * as alertsApi from '../../services/alertsApi'
import * as gameApi from '../../services/gameApi'
import { emit } from '../../telemetry/client'
import { _resetStoryCache } from '../../utils/storyCache'
import { sortWatches } from '../../utils/watchSort'
import AlertsV2Header from './AlertsV2Header'
import WatchCardExtras from './WatchCardExtras'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const STORY = {
  kind: 'flight', watch_id: 7, currency: 'USD', mode: 'any_drop', target: null,
  points: [{ at: '2026-11-01T10:00:00Z', price: 500 }, { at: '2026-11-02T10:00:00Z', price: 430 }], baseline: 500,
  latest: { at: '2026-11-02T10:00:00Z', price: 430 }, lowest: { at: '2026-11-02T10:00:00Z', price: 430 },
  typical: { low: 390, high: 520, source: 'google' }, verdict: 'good', advice: { code: 'at_lowest', params: {} },
  checked_days_ago: 1, pending_first_check: false, estimate: null, caught: null, live_prices: true,
}

let root; let host
const io = { list: [] }
const see = async () => { await act(async () => { io.list.forEach((o) => o.cb([{ isIntersecting: true }])) }) }
const render = async (el) => { await act(async () => { root.render(el) }) }
const q = (tid) => host.querySelector(`[data-tid="${tid}"]`)

beforeEach(() => {
  host = document.createElement('div'); document.body.appendChild(host); root = createRoot(host)
  state.live = true; state.hide = false; state.me = null
  window.matchMedia = () => ({ matches: true, addEventListener() {}, removeEventListener() {} })
  window.requestAnimationFrame = (f) => setTimeout(f, 0); window.cancelAnimationFrame = clearTimeout
  vi.clearAllMocks()
  _resetStoryCache()
  io.list = []
  window.IntersectionObserver = class { constructor(cb) { this.cb = cb; io.list.push(this) } observe() {} disconnect() {} }
  alertsApi.getSavings.mockResolvedValue({ total_usd: 0, by_currency: {}, drops_caught: 0 })
  alertsApi.getStory.mockResolvedValue(STORY)
  gameApi.getGameCatalog.mockResolvedValue({ badges: [
    { id: 'deal_hunter', target: 1 }, { id: 'deal_hunter_silver', target: 5 }, { id: 'bullseye', target: 1 }, { id: 'level_up', target: 3 },
  ] })
})
afterEach(() => { act(() => root.unmount()); host.remove() })

const header = (url = '/alerts', props = {}) => render(<MemoryRouter key={url} initialEntries={[url]}><AlertsV2Header {...props} /></MemoryRouter>)

describe('Alerts hub header', () => {
  it('paused banner without live prices', async () => {
    state.live = false
    await header()
    const b = q('alerts.live-paused')
    expect(b.textContent).toContain('Live checks paused')
    expect(b.textContent).toContain('each shows when it was checked')
    state.live = true
    await header()
    expect(q('alerts.live-paused')).toBeNull()
  })

  it('sort chips report the choice; departing soon orders by date', async () => {
    const onSort = vi.fn()
    await header('/alerts', { sort: 'moving', onSort })
    await act(async () => { q('alerts.sort-soon').dispatchEvent(new MouseEvent('click', { bubbles: true })) })
    expect(onSort).toHaveBeenCalledWith('soon')
    const list = [{ id: 1, departure_date: '2027-03-01' }, { id: 2, kind: 'hotel', expires_on: '2026-12-01' }, { id: 3 }, { id: 4, departure_date: '2026-11-20' }]
    expect(sortWatches(list, 'soon').map((w) => w.id)).toEqual([4, 2, 1, 3])
    expect(sortWatches([{ id: 1, created_at: 'a' }, { id: 2, created_at: 'b' }], 'newest').map((w) => w.id)).toEqual([2, 1])
    const moving = [
      { id: 1, history: [{ price: 100 }, { price: 101 }] }, { id: 2, history: [{ price: 100 }, { price: 80 }] },
    ]
    expect(sortWatches(moving, 'moving').map((w) => w.id)).toEqual([2, 1])
  })

  it('deal hunter shows the next badge and is hidden with hide_game', async () => {
    state.me = { badges: [{ id: 'deal_hunter', progress: 1, target: 1, earned: true }, { id: 'deal_hunter_silver', progress: 3, target: 5, earned: false }] }
    await header()
    await act(async () => {})
    const t = q('alerts.deal-hunter')
    expect(t).not.toBeNull()
    expect(t.querySelector('[role="progressbar"]').getAttribute('aria-valuenow')).toBe('3')
    expect(t.textContent).toContain('3 of 5')
    expect(t.textContent).not.toContain('level_up')
    state.hide = true
    await header()
    expect(q('alerts.deal-hunter')).toBeNull()
  })

  it('digest notification opens the hub with via email_link', async () => {
    await header('/alerts?from=digest')
    expect(host.querySelector('[data-testid="digest-entry"]')).not.toBeNull()
    expect(emit).toHaveBeenCalledWith('alert_digest_open', { via: 'email_link' })
    await header('/alerts?from=digest&via=in_app')
    expect(emit).toHaveBeenCalledWith('alert_digest_open', { via: 'in_app' })
    await header('/alerts')
    expect(host.querySelector('[data-testid="digest-entry"]')).toBeNull()
  })

  it('preferences button opens the panel', async () => {
    alertsApi.getAlertPrefs.mockResolvedValue({ digest_weekly: false, digest_push: false, digest_day: 1, instant: 'all',
      quiet_hours: { enabled: false, start: '22:00', end: '07:00' }, daily_cap: { flight: 3, hotel: 3, activity: 3, trip: 3 },
      group_window_min: 15, timezone: null, quiet_hours_active: false })
    await header()
    expect(host.querySelector('[data-testid="prefs-region"]')).toBeNull()
    await act(async () => { q('alerts.prefs-toggle').dispatchEvent(new MouseEvent('click', { bubbles: true })) })
    expect(host.querySelector('[data-testid="prefs-region"]')).not.toBeNull()
  })
})

describe('WatchCardExtras', () => {
  const mount = (url, watch = { id: 7, last_checked_at: new Date().toISOString() }) =>
    render(<MemoryRouter initialEntries={[url]}><article><WatchCardExtras watch={watch} /></article></MemoryRouter>)

  it('shows the verdict chip and expands the story on tap', async () => {
    await mount('/alerts')
    await see()
    expect(host.querySelector('[data-testid="extras-verdict"]').textContent).toBe('Good price')
    expect(q('alerts.story-toggle').getAttribute('aria-expanded')).toBe('false')
    await act(async () => { q('alerts.story-toggle').dispatchEvent(new MouseEvent('click', { bubbles: true })) })
    expect(host.querySelector('[data-testid="extras-story"]')).not.toBeNull()
  })

  it('deep link expands the story', async () => {
    const scroll = vi.fn()
    Element.prototype.scrollIntoView = scroll
    await mount('/alerts?watch=flight:7')
    await act(async () => { await new Promise((r) => setTimeout(r, 5)) })
    expect(q('alerts.story-toggle').getAttribute('aria-expanded')).toBe('true')
    expect(scroll).toHaveBeenCalled()
  })

  it('a link to another watch leaves it closed', async () => {
    await mount('/alerts?watch=hotel:7')
    expect(q('alerts.story-toggle').getAttribute('aria-expanded')).toBe('false')
  })

  it('says it is waiting when there is no look yet', async () => {
    alertsApi.getStory.mockRejectedValue(new Error('x'))
    await mount('/alerts', { id: 7, kind: 'hotel', last_checked_at: null })
    await see()
    expect(host.querySelector('[data-testid="extras-checked"]').textContent).toBe('Waiting for the first price check')
    expect(host.querySelector('[data-testid="extras-verdict"]')).toBeNull()
  })
})

describe('lazy story loading', () => {
  const mount = (watch) => render(<MemoryRouter><article><WatchCardExtras watch={watch} /></article></MemoryRouter>)

  it('does not fetch until the card is seen, then fetches once', async () => {
    await mount({ id: 7, last_checked_at: 'x' })
    expect(alertsApi.getStory).not.toHaveBeenCalled()
    await see()
    expect(alertsApi.getStory).toHaveBeenCalledTimes(1)
  })

  it('falls back to fetch-on-expand without IntersectionObserver', async () => {
    delete window.IntersectionObserver
    await mount({ id: 8, last_checked_at: 'x' })
    expect(alertsApi.getStory).not.toHaveBeenCalled()
    await act(async () => { q('alerts.story-toggle').dispatchEvent(new MouseEvent('click', { bubbles: true })) })
    expect(alertsApi.getStory).toHaveBeenCalledTimes(1)
  })

  it('shares the cache per kind:id:last_checked_at and limits concurrency to 3', async () => {
    const { loadStory } = await import('../../utils/storyCache')
    const done = []
    alertsApi.getStory.mockImplementation(() => new Promise((r) => { done.push(r) }))
    const ps = [1, 2, 3, 4, 5].map((i) => loadStory('t', 'flight', i, 's'))
    loadStory('t', 'flight', 1, 's')
    expect(alertsApi.getStory).toHaveBeenCalledTimes(3)
    await act(async () => { done[0](STORY); await ps[0] })
    expect(alertsApi.getStory).toHaveBeenCalledTimes(4)
    loadStory('t', 'flight', 1, 'newer')
    expect(alertsApi.getStory.mock.calls.length).toBeLessThanOrEqual(5)
  })
})
