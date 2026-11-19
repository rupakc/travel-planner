// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import '../i18n'

const config = { current: { features: { carbon: 1 } } }
vi.mock('../hooks/useClientConfig', () => ({
  useClientConfig: () => ({ config: config.current, loaded: true }),
  featureOn: (c, name) => c?.features?.[name] === true || c?.features?.[name] === 1,
}))
const fetchTripCarbon = vi.fn()
vi.mock('../services/api', () => ({
  fetchTripCarbon: (...a) => fetchTripCarbon(...a),
}))

import CarbonFootprint from './CarbonFootprint'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const ANSWER = {
  total_kg: 1000,
  per_person_kg: 500,
  travellers: 2,
  nights: 4,
  diet: 'mixed',
  cabin: 'economy',
  categories: [
    { key: 'flights', kg: 600, share: 0.6, included: true },
    { key: 'stays', kg: 250, share: 0.25, included: true },
    { key: 'ground', kg: 50, share: 0.05, included: true },
    { key: 'food', kg: 100, share: 0.1, included: true },
    { key: 'activities', kg: 0, share: 0, included: false },
  ],
  lines: [
    { category: 'flights', kind: 'flight_tim', label: 'Flight LHR–CDG (Google TIM)', kg: 600, method: 'measured_tim', source: 'google_tim', params: { route: 'LHR–CDG' } },
    { category: 'stays', kind: 'hotel_nights', label: 'Hotel', kg: 250, method: 'factor', source: 'desnz_2026', params: { city: 'Paris', nights: 4, rooms: 1 } },
    { category: 'food', kind: 'meals', label: 'Meals', kg: 100, method: 'estimate', source: 'owid_food', params: { diet: 'mixed', days: 4, travellers: 2 } },
  ],
  comparisons: { car_km: 6027, annual_budget_kg: 2000, budget_share: 0.25 },
  lower_carbon: [{ route: 'LHR–CDG', from: 'LHR', to: 'CDG', rail_km: 417, flight_kg: 600, rail_kg: 19, saving_kg: 581, legs: 2 }],
  sources: [
    { id: 'google_tim', name: 'Travel Impact Model', url: 'https://travelimpactmodel.org', attribution: 'Emissions estimates: Google Travel Impact Model, CC BY-SA 4.0' },
    { id: 'desnz_2026', name: 'UK Government GHG Conversion Factors 2026', url: 'https://assets.publishing.service.gov.uk/x.xlsx', licence: 'Open Government Licence v3.0', attribution: 'Contains public sector information licensed under the Open Government Licence v3.0' },
  ],
  assumptions: [{ code: 'rooms_default', text: '1 room(s): one per two travellers.', params: { rooms: 1 } }],
}

const SEARCH = { origin: 'London', destination: 'Paris', departure_date: '2026-05-01', return_date: '2026-05-05', num_travelers: 2 }
const RESULTS = {
  flights: { results: [{ price_usd: 1, airline: 'AF', outbound: { origin: 'LHR', destination: 'CDG', stops: 0, layovers: [], airline: 'AF' } }, { price_usd: 2 }] },
  hotels: { results: [{ name: 'H', city: 'Paris', price_per_night_usd: 100, amenities: ['wifi'] }] },
  itinerary: { days: [{ slots: [{ activity: 'Louvre', lat: 48.86, lng: 2.33, notes: 'x' }] }] },
}

describe('CarbonFootprint', () => {
  let container, root
  const render = async (props) => {
    await act(async () => root.render(<CarbonFootprint searchData={SEARCH} results={RESULTS} {...props} />))
    await act(async () => { await vi.advanceTimersByTimeAsync(400) })
  }
  const q = (sel) => container.querySelector(sel)

  beforeEach(() => {
    vi.useFakeTimers()
    config.current = { features: { carbon: 1 } }
    fetchTripCarbon.mockReset()
    fetchTripCarbon.mockResolvedValue(ANSWER)
    try { localStorage.removeItem('tp_carbon_diet') } catch { /* jsdom */ }
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
  })
  afterEach(() => {
    act(() => root.unmount())
    container.remove()
    vi.useRealTimers()
  })

  it('is hidden and never calls an older backend without features.carbon', async () => {
    config.current = { features: {} }
    await render()
    expect(container.innerHTML).toBe('')
    expect(fetchTripCarbon).not.toHaveBeenCalled()
  })

  it('hides itself when the endpoint answers 404', async () => {
    fetchTripCarbon.mockRejectedValue({ response: { status: 404 } })
    await render()
    expect(container.innerHTML).toBe('')
  })

  it('sends a trimmed result summary and shows the total, bar and comparisons', async () => {
    await render()
    const body = fetchTripCarbon.mock.calls[0][0]
    expect(body.search).toEqual(SEARCH)
    expect(body.results.flights.results).toHaveLength(1)
    expect(body.results.flights.results[0].outbound).toEqual({ origin: 'LHR', destination: 'CDG', stops: 0, layovers: [] })
    expect(body.results.hotels.results).toEqual([{ name: 'H', city: 'Paris' }])
    expect(body.itinerary).toEqual({ days: [{ slots: [{ activity: 'Louvre', lat: 48.86, lng: 2.33 }] }] })
    expect(body.diet).toBe('mixed')

    expect(q('[data-testid="carbon-total"]').textContent).toBe('≈ 1,000 kg CO₂e')
    expect(container.textContent).toContain('500 kg per person')
    expect(q('[data-testid="carbon-bar-flights"]').style.width).toBe('60%')
    expect(q('[data-testid="carbon-bar-activities"]')).toBeNull()
    expect(container.textContent).toContain('Like driving 6,027 km in an average car')
    expect(container.textContent).toContain('25% of a 2 t yearly budget per person')
  })

  it('shows the train hint when the backend found one', async () => {
    await render()
    const hint = q('[data-testid="carbon-rail-hint"]')
    expect(hint.textContent).toContain('LHR–CDG')
    expect(hint.textContent).toContain('581 kg')
  })

  it('"How we calculate" lists methods, assumptions and the attribution', async () => {
    await render()
    expect(q('[data-testid="carbon-attribution-desnz_2026"]')).toBeNull()
    const how = q('[data-tid="carbon.how"]')
    expect(how.getAttribute('aria-expanded')).toBe('false')
    await act(async () => how.click())
    expect(how.getAttribute('aria-expanded')).toBe('true')
    expect(container.textContent).toContain('Google TIM')
    expect(container.textContent).toContain('Estimate')
    expect(container.textContent).toContain('Stay in Paris: nights 4, rooms 1')
    expect(container.textContent).toContain('Rooms: 1 (one per two travellers).')
    expect(q('[data-testid="carbon-attribution-desnz_2026"]').textContent)
      .toBe('Contains public sector information licensed under the Open Government Licence v3.0')
    expect(q('a[href="https://travelimpactmodel.org"]')).not.toBeNull()
    await act(async () => document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })))
    expect(how.getAttribute('aria-expanded')).toBe('false')
  })

  it('changing the diet recomputes and is remembered', async () => {
    await render()
    const select = q('[data-tid="carbon.diet"]')
    await act(async () => {
      select.value = 'vegan'
      select.dispatchEvent(new Event('change', { bubbles: true }))
    })
    await act(async () => { await vi.advanceTimersByTimeAsync(400) })
    expect(fetchTripCarbon).toHaveBeenCalledTimes(2)
    expect(fetchTripCarbon.mock.calls[1][0].diet).toBe('vegan')
    expect(localStorage.getItem('tp_carbon_diet')).toBe('vegan')
  })

  it('plan mode sends the selections', async () => {
    const selections = {
      flight: { price_usd: 1, outbound: { origin: 'LHR', destination: 'CDG', emissions: { kg_co2e_per_pax: 50 } } },
      hotel: { name: 'H', price_per_night_usd: 90, country_code: 'FR' },
      getting_around: [{ name: 'Metro', type: 'metro', scope: 'intra_city', description: 'long' }],
      activities: [{ name: 'Seine cruise', price_usd: 20 }],
    }
    await render({ mode: 'plan', compact: true, selections, results: undefined })
    const body = fetchTripCarbon.mock.calls[0][0]
    expect(body.results).toBeUndefined()
    expect(body.selections.flight.outbound.emissions).toEqual({ kg_co2e_per_pax: 50 })
    expect(body.selections.hotel).toEqual({ name: 'H', country_code: 'FR' })
    expect(body.selections.getting_around).toEqual([{ type: 'metro', scope: 'intra_city' }])
    expect(body.selections.activities).toEqual([{ name: 'Seine cruise' }])
  })

  it('an answer without crawler data shows no source line (older or crawler-off backend)', async () => {
    await render()
    expect(q('[data-testid="carbon-live-sources"]')).toBeNull()
    await act(async () => q('[data-tid="carbon.how"]').click())
    expect(q('[data-testid="official-source"]')).toBeNull()
  })

  it('shows the source of crawler numbers on the card and on their lines', async () => {
    const grid = {
      id: 'crawler_grid_carbon_ember_grid_is', name: 'Ember yearly electricity data',
      url: 'https://ember-energy.org/data/yearly-electricity-data/', as_of: '2026-10-01',
      licence: 'CC-BY-4.0', attribution: 'Ember, CC BY 4.0',
    }
    fetchTripCarbon.mockResolvedValue({
      ...ANSWER,
      lines: [
        ...ANSWER.lines.filter((ln) => ln.kind !== 'hotel_nights'),
        { category: 'stays', kind: 'hotel_nights', label: 'Hotel', kg: 7.8, method: 'estimate', source: grid.id, crawler_source: grid, params: { city: 'Reykjavik', nights: 4, rooms: 1, grid_g_per_kwh: 28 } },
      ],
      assumptions: [{ code: 'hotel_grid', text: 'x', params: { city: 'Reykjavik', g_per_kwh: 28, kwh: 70 } }],
      sources: [...ANSWER.sources, grid],
      crawler_sources: [grid],
    })
    await render()
    const live = q('[data-testid="carbon-live-sources"]')
    expect(live.textContent).toContain('Includes newer official data from the Voyager crawler:')
    expect(live.textContent).toContain('Source: Ember yearly electricity data')
    expect(live.textContent).toContain('Ember, CC BY 4.0')
    expect(live.querySelector('a').getAttribute('href')).toBe(grid.url)
    await act(async () => q('[data-tid="carbon.how"]').click())
    expect(container.querySelectorAll('[data-testid="official-source"]')).toHaveLength(2)
    // "via" is SourceLine's forex pivot currency, never shown for carbon
    expect(container.textContent).not.toMatch(/\bvia\b/)
    expect(container.textContent).toContain(
      "No hotel-stay factor for Reykjavik: the country's electricity grid (28 g CO₂e/kWh) × 70 kWh-equivalent per room-night.",
    )
  })

  it('tolerates a malformed crawler_sources field', async () => {
    fetchTripCarbon.mockResolvedValue({ ...ANSWER, crawler_sources: 'x' })
    await render()
    expect(q('[data-testid="carbon-total"]')).not.toBeNull()
    expect(q('[data-testid="carbon-live-sources"]')).toBeNull()
  })

  it('shows a quiet error on other failures', async () => {
    fetchTripCarbon.mockRejectedValue({ response: { status: 500 } })
    await render()
    expect(container.textContent).toContain("The footprint isn't available right now.")
  })
})
