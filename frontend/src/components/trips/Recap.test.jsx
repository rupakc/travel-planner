// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'

vi.mock('../../hooks/useJourney', () => ({ useJourney: () => ({ enabled: true, loaded: true }) }))
vi.mock('../../services/tripsApi', () => ({ getRecap: vi.fn(), completeRecap: vi.fn() }))
vi.mock('../../services/api', () => ({ discoverDestinations: vi.fn() }))
vi.mock('../../game/announce', () => ({ announceGame: vi.fn() }))
vi.mock('../../telemetry/client', () => ({ emit: vi.fn() }))
vi.mock('./RecapMap', () => ({ default: ({ points }) => <div data-testid="map">{points.length}</div> }))

import Recap from './Recap'
import { getRecap, completeRecap } from '../../services/tripsApi'
import { discoverDestinations } from '../../services/api'
import { announceGame } from '../../game/announce'
import { emit } from '../../telemetry/client'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const TRIP = { id: 12, destination: 'Lisbon', destinations: ['Lisbon'], num_travelers: 2, budget_usd: 3000, origin: 'NYC' }
const RECAP = {
  trip_id: 12, title: 'Lisbon in spring', start_date: '2026-10-01', end_date: '2026-10-08', days: 8, nights: 7,
  places: [], visited_count: 9, rated_count: 7, avg_stars: 4.3, route: [[38.7, -9.14], [38.71, -9.15]], distance_km: 41.2,
  countries: [{ code: 'PT', name: 'Portugal', new: true }], continents: ['EU'],
  spend: { budget_usd: 3000, plan_cost_usd: null, spent_usd: '2140.50', by_category_usd: {}, unconverted: ['GBP'] },
  journal_count: 5, checkin_days: 6, completed_at: null, can_complete: true,
}
const PLAN = { search_data: { origin: 'NYC', nationality: 'American', interests: ['food'] }, selections: { hotel: { total_price_usd: 700 } } }

let container, root
const text = () => container.textContent
const tid = (id) => container.querySelector(`[data-tid="${id}"]`)
const flush = () => act(async () => { await new Promise((r) => setTimeout(r, 0)) })
const click = async (el) => { await act(async () => { el.click() }); await flush() }

async function mount(recap = RECAP) {
  getRecap.mockResolvedValue(recap)
  await act(async () => root.render(<MemoryRouter><Recap trip={TRIP} token="tok" /></MemoryRouter>))
  await flush()
}

beforeEach(() => {
  vi.clearAllMocks()
  globalThis.fetch = vi.fn(async (url, opts) => {
    if (String(url).endsWith('/share')) return { ok: true, json: async () => ({ share_token: 'abc' }) }
    return { ok: true, json: async () => PLAN }
  })
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
    await act(async () => root.unmount())
    root = createRoot(container)
    await mount()
    await click(tid('recap.finish'))
    expect(tid('recap.reveal')).toBeNull()
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
    expect(fetch.mock.calls.filter(([u]) => String(u).endsWith('/share'))).toHaveLength(1)
  })
})
