// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'

vi.mock('../../hooks/useJourney', () => ({ useJourney: () => ({ enabled: true, loaded: true }) }))
vi.mock('../../services/tripsApi', () => ({ getRecap: vi.fn(), completeRecap: vi.fn() }))
vi.mock('../../services/api', () => ({ discoverDestinations: vi.fn(), sharePlan: vi.fn() }))
vi.mock('../../game/announce', () => ({ announceGame: vi.fn() }))
vi.mock('../../context/AuthContext', () => ({ useOptionalAuth: () => globalThis.__testAuth || {} }))
vi.mock('../../telemetry/client', () => ({ emit: vi.fn() }))
vi.mock('./RecapMap', () => ({ default: ({ points }) => <div data-testid="map">{points.length}</div> }))

import Recap from './Recap'
import { getRecap, completeRecap } from '../../services/tripsApi'
import { discoverDestinations, sharePlan } from '../../services/api'
import { announceGame } from '../../game/announce'
import { emit } from '../../telemetry/client'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const PLAN = { search_data: { origin: 'NYC', nationality: 'American', interests: ['food'] }, selections: { hotel: { total_price_usd: 700 } } }
const TRIP = { id: 12, destination: 'Lisbon', destinations: ['Lisbon'], num_travelers: 2, budget_usd: 3000, origin: 'NYC', ...PLAN }
const RECAP = {
  trip_id: 12, title: 'Lisbon in spring', start_date: '2026-10-01', end_date: '2026-10-08', days: 8, nights: 7,
  places: [], visited_count: 9, rated_count: 7, avg_stars: 4.3, route: [[38.7, -9.14], [38.71, -9.15]], distance_km: 41.2,
  countries: [{ code: 'PT', name: 'Portugal', new: true }], continents: ['EU'],
  spend: { budget_usd: 3000, plan_cost_usd: null, spent_usd: '2140.50', by_category_usd: {}, unconverted: ['GBP'] },
  journal_count: 5, checkin_days: 6, completed_at: null, can_complete: true,
}
let container, root
const text = () => container.textContent
const tid = (id) => container.querySelector(`[data-tid="${id}"]`)
const flush = () => act(async () => { await new Promise((r) => setTimeout(r, 0)) })
const click = async (el) => { await act(async () => { el.click() }); await flush() }

async function mount(recap = RECAP, trip = TRIP) {
  getRecap.mockResolvedValue(recap)
  await act(async () => root.render(<MemoryRouter><Recap trip={trip} token="tok" /></MemoryRouter>))
  await flush()
}

beforeEach(() => {
  vi.clearAllMocks()
  sharePlan.mockResolvedValue({ share_token: 'abc' })
  window.matchMedia = vi.fn(() => ({ matches: false }))
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})
afterEach(() => {
  act(() => root.unmount()); container.remove()
  delete navigator.share
})

describe('Recap', () => {
  it('shows stats, labelled estimates and unconverted currencies', async () => {
    await mount()
    expect(tid('recap.stat-days').textContent).toContain('8')
    expect(tid('recap.stat-distance').textContent).toContain('41.2')
    expect(text()).toContain('Estimates')
    expect(tid('recap.unconverted').textContent).toContain('GBP')
    expect(tid('recap.plan-cost')).not.toBeNull()
    expect(emit).toHaveBeenCalledWith('recap_action', { action: 'view' })
  })

  it('shows the not-ready message before the trip ends', async () => {
    await mount({ ...RECAP, can_complete: false })
    expect(tid('recap.not-ready').textContent).toMatch(/Your recap appears after/)
    expect(tid('recap.finish')).toBeNull()
  })

  it('finish completes, announces the game delta and reveals new countries', async () => {
    completeRecap.mockResolvedValue({ completed_at: 'now', new_countries: ['PT'], game: { awards: [{ rule: 'recap_complete' }] } })
    await mount()
    await click(tid('recap.finish'))
    expect(announceGame).toHaveBeenCalledWith({ awards: [{ rule: 'recap_complete' }] })
    expect(tid('recap.reveal').textContent).toContain('Portugal')
    expect(tid('recap.finish')).toBeNull()
  })

  it('a repeat completion shows no reveal', async () => {
    await mount({ ...RECAP, completed_at: '2026-10-09T00:00:00Z', can_complete: false })
    expect(tid('recap.finish')).toBeNull()
    expect(tid('recap.reveal')).toBeNull()
    completeRecap.mockResolvedValue({ completed_at: 'x', new_countries: [], game: null })
  })

  it('a second completion call (empty new_countries) shows no reveal', async () => {
    completeRecap.mockResolvedValueOnce({ completed_at: 'x', new_countries: ['PT'], game: { awards: [{ rule: 'recap_complete' }] } })
    completeRecap.mockResolvedValueOnce({ completed_at: 'x', new_countries: [], game: null })
    await mount()
    await click(tid('recap.finish'))
    await click(tid('recap.reveal-close'))
    expect(tid('recap.reveal')).toBeNull()
    announceGame.mockClear()
    // the server is idempotent: simulate the same call again
    await act(async () => { const r = await completeRecap('tok', 12); expect(r.new_countries).toEqual([]) })
    expect(tid('recap.reveal')).toBeNull()
    expect(announceGame).not.toHaveBeenCalled()
  })

  it('where next asks for a home airport when the trip has none', async () => {
    await mount(RECAP, { ...TRIP, origin: undefined, search_data: {} })
    await click(tid('recap.where-next-go'))
    expect(discoverDestinations).not.toHaveBeenCalled()
    expect(container.textContent).toContain('home airport')
  })

  it('where next falls back to the saved home airport', async () => {
    globalThis.__testAuth = { user: { id: 'u1' }, preferences: {} }
    window.localStorage.setItem('tp_home_airport_u1', 'LIS')
    discoverDestinations.mockResolvedValue({ destinations: [] })
    try {
      await mount(RECAP, { ...TRIP, origin: undefined, search_data: {} })
      await click(tid('recap.where-next-go'))
      expect(discoverDestinations.mock.calls[0][0]).toMatchObject({ origin: 'LIS' })
    } finally {
      delete globalThis.__testAuth
      window.localStorage.removeItem('tp_home_airport_u1')
    }
  })

  it('works without selections or search_data on the trip', async () => {
    await mount({ ...RECAP, route: [] }, { id: 12, destination: 'Lisbon' })
    expect(tid('recap.stats')).not.toBeNull()
    expect(tid('recap.plan-cost')).toBeNull()
  })

  it('reduced motion renders a static list', async () => {
    window.matchMedia = vi.fn(() => ({ matches: true }))
    completeRecap.mockResolvedValue({ completed_at: 'now', new_countries: ['PT'], game: null })
    await mount()
    await click(tid('recap.finish'))
    expect(tid('recap.reveal-list')).not.toBeNull()
    expect(tid('recap.stamp-PT')).toBeNull()
  })

  it('where next sends no request until tapped, then drops the current destination', async () => {
    discoverDestinations.mockResolvedValue({ destinations: [{ city: 'Lisbon', country: 'Portugal' }, { city: 'Porto', country: 'Portugal' }] })
    await mount()
    expect(discoverDestinations).not.toHaveBeenCalled()
    await click(tid('recap.where-next-go'))
    expect(discoverDestinations).toHaveBeenCalledTimes(1)
    expect(discoverDestinations.mock.calls[0][0]).toMatchObject({ budget_usd: 3000, interests: ['food'] })
    const list = tid('recap.where-next-list')
    expect(list.textContent).toContain('Porto')
    expect(list.textContent).not.toContain('Lisbon')
    expect(list.querySelector('a').getAttribute('href')).toBe('/explore')
  })

  it('share falls back to copying the link', async () => {
    const writeText = vi.fn().mockResolvedValue()
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    await mount()
    await click(tid('recap.share'))
    expect(writeText).toHaveBeenCalledWith(`${window.location.origin}/share/abc`)
    expect(tid('recap.msg').textContent).toContain('copied')
  })

  it('share uses navigator.share when present and reuses the link', async () => {
    navigator.share = vi.fn().mockResolvedValue()
    await mount()
    await click(tid('recap.share'))
    await click(tid('recap.share'))
    expect(navigator.share).toHaveBeenCalledTimes(2)
    expect(navigator.share.mock.calls[0][0]).toMatchObject({ text: '8 days in Lisbon · 9 places', url: `${window.location.origin}/share/abc` })
    expect(sharePlan).toHaveBeenCalledTimes(1)
  })
})
