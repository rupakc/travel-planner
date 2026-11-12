// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'

const v2 = vi.hoisted(() => ({ on: true, livePrices: true }))
vi.mock('../hooks/useAlertsV2', () => ({ useAlertsV2: () => v2 }))
vi.mock('../hooks/useAirportCities', () => ({ useAirportCities: () => (c) => c }))
vi.mock('../components/alerts/WatchHotelButton', () => ({ default: ({ hotel }) => <span data-testid="classic-hotel">{hotel.name}</span> }))
vi.mock('../components/alerts/WatchActivityButton', () => ({ default: ({ activity }) => <span data-testid="classic-activity">{activity.name}</span> }))
vi.mock('../components/alerts2/QuickWatchButton', () => ({
  default: (p) => <span data-testid="quick" data-kind={p.kind} data-plan={String(p.planId)} data-spec={JSON.stringify(p.spec)}>{p.title}</span>,
}))
vi.mock('../components/alerts/WatchFareButton', () => ({ default: () => <span data-testid="classic-fare" /> }))
vi.mock('../components/alerts2/WatchSuggestions', () => ({
  default: (p) => <span data-testid="suggest" data-plan={p.planId} data-force={String(!!p.force)} />,
}))

import { HotelsSection, MyPlanDrawer } from './ResultsPage'
import { hotelWatchSpec } from '../utils/hotelWatch'
import { tripFromSearch } from '../utils/fareWatch'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const SEARCH = { destination: 'Lisbon', departure_date: '2099-12-10', return_date: '2099-12-14', adults: 2 }
const SEARCH2 = { origin: 'NYC', destination: 'LIS', departure_date: '2099-12-10', return_date: '2099-12-14', num_travelers: 2 }
const HOTEL = { name: 'Lumen Hotel', price_per_night_usd: 100 }
const sel = { flight: null, flights: [], hotel: null, activities: [], places_to_see: [], sim: null, tips: [], getting_around: [], events: [], walking_tours: [], itinerary_slots: [], itinerary_notes: {}, itinerary_edits: {} }

let container, root
beforeEach(() => {
  v2.on = true; v2.livePrices = true
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  vi.stubGlobal('fetch', vi.fn(async (url, init) => ({ ok: true, json: async () => (init?.method === 'POST' ? { id: 5 } : []) })))
})
afterEach(() => { act(() => root.unmount()); container.remove(); vi.unstubAllGlobals() })
const render = (el) => act(() => root.render(<MemoryRouter>{el}</MemoryRouter>))
const q = (id) => [...container.querySelectorAll(`[data-testid="${id}"]`)]
const hotels = () => <HotelsSection data={{ results: [HOTEL] }} selections={sel} onSelect={() => {}} searchData={SEARCH} />
const drawer = (extra = {}) => (
  <MyPlanDrawer isOpen onClose={() => {}} selections={{ ...sel, hotel: HOTEL }} planName="Lisbon" onPlanNameChange={() => {}}
    onRemoveSelection={() => {}} onViewPlan={() => {}} token="tok" searchData={SEARCH} results={{}} loadedPlanId={null}
    onLoadPlan={() => {}} onClearLoadedPlan={() => {}} onClearSelections={() => {}} {...extra} />
)

describe('Results one-tap watch', () => {
  it('flag off renders exactly the classic buttons', async () => {
    v2.on = false
    await render(hotels())
    const off = container.innerHTML
    expect(q('classic-hotel')).toHaveLength(1)
    expect(q('quick')).toHaveLength(0)
    await render(drawer())
    expect(q('quick')).toHaveLength(0)
    expect(q('suggest')).toHaveLength(0)
    expect(off).not.toContain('data-testid="quick"')
  })

  it('quick watch spec equals the dialog spec for a hotel', async () => {
    await render(hotels())
    const quick = q('quick')
    expect(quick).toHaveLength(1)
    expect(q('classic-hotel')).toHaveLength(1)
    expect(JSON.parse(quick[0].dataset.spec)).toEqual(hotelWatchSpec(HOTEL, SEARCH))
    expect(quick[0].dataset.kind).toBe('hotel')
  })

  it('suggestions after save, once', async () => {
    await render(drawer())
    expect(q('suggest')).toHaveLength(0)
    const save = [...container.querySelectorAll('button')].find((b) => /Save Plan/i.test(b.textContent))
    await act(async () => { save.click() })
    await act(async () => {})
    expect(q('suggest')).toHaveLength(1)
    expect(q('suggest')[0].dataset.plan).toBe('5')
    expect(q('suggest')[0].dataset.force).toBe('false')
  })

  it('flight quick spec equals the dialog spec (the trip object); flag off has classic only', async () => {
    const el = () => drawer({ selections: { ...sel, flight: { airline: 'Air', price_usd: 500 } }, searchData: SEARCH2 })
    await render(el())
    const quick = q('quick').filter((n) => n.dataset.kind === 'flight')
    expect(quick).toHaveLength(1)
    expect(JSON.parse(quick[0].dataset.spec)).toEqual(JSON.parse(JSON.stringify(tripFromSearch(SEARCH2))))
    expect(q('classic-fare')).toHaveLength(1)
    v2.on = false
    await render(el())
    expect(q('quick')).toHaveLength(0)
    expect(q('classic-fare')).toHaveLength(1)
  })
})
