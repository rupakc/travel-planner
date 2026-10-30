// @vitest-environment node
import { describe, it, expect } from 'vitest'
import { buildStressTestPayload, recheckFingerprint, recheckErrorMessage } from './stressTestPayload'
import { moveSlot, removeSlot } from './itineraryLayout'

const slot = (time_of_day, activity, cost) => ({
  time_of_day, activity, location: `${activity} St`, duration_hours: 2, notes: `About ${activity}`, estimated_cost_usd: cost,
})

const ITIN = {
  days: [
    { day_number: 1, date: '2027-05-01', city: 'Lisbon', slots: [slot('morning', 'Castle', 10), slot('afternoon', 'Tram 28', 5), slot('evening', 'Fado', 30)] },
    { day_number: 2, date: '2027-05-02', city: 'Lisbon', slots: [slot('morning', 'Belem', 15), slot('afternoon', 'LX Factory', 0)] },
  ],
  total_estimated_cost_usd: 60,
  verification: { level: 'unverified' },
}

const SEARCH = {
  origin: 'LHR', destination: 'Lisbon', departure_date: '2027-05-01', return_date: '',
  interests: ['food'], nationality: 'British', budget_usd: 2000, num_travelers: 2,
}

const RESULTS = {
  itinerary: ITIN,
  flights: { results: [{ price_usd: 120 }], verification: { level: 'partial', checks: [] } },
  visa: { visa_required: false, verification: { level: 'verified' } },
  weather: { daily: [{ date: '2027-05-01' }], verification: { level: 'unverified' } },
  hotels: { results: [{ name: 'H' }] },
  stress_test: { overall: 'green', findings: [] },
}

const selections = (over = {}) => ({ itinerary_layout: null, itinerary_edits: {}, ...over })
const activities = (payload) => payload.itinerary.days.map((d) => d.slots.map((s) => s.activity))

describe('buildStressTestPayload', () => {
  it('sends the search request with the ARRANGED days', () => {
    const layout = moveSlot(ITIN, null, '1-morning', 2, 'evening')
    const p = buildStressTestPayload(SEARCH, RESULTS, selections({ itinerary_layout: layout }))
    expect(p.origin).toBe('LHR')
    expect(p.destination).toBe('Lisbon')
    expect(p.num_travelers).toBe(2)
    expect(activities(p)).toEqual([['Tram 28', 'Fado'], ['Belem', 'LX Factory', 'Castle']])
    expect(p.itinerary.days[1].slots[2].time_of_day).toBe('evening')
    expect(p.itinerary.days[0].daily_estimated_cost_usd).toBe(35)
  })

  it('applies itinerary_edits to activity, location and cost', () => {
    const layout = moveSlot(ITIN, null, '1-morning', 2, 'evening')
    const edits = { '1-morning': { activity: 'Castle sunset', location: 'Alfama', cost: 25 }, '2-morning': { cost: null } }
    const p = buildStressTestPayload(SEARCH, RESULTS, selections({ itinerary_layout: layout, itinerary_edits: edits }))
    const moved = p.itinerary.days[1].slots[2]
    expect(moved).toMatchObject({ activity: 'Castle sunset', location: 'Alfama', estimated_cost_usd: 25, time_of_day: 'evening' })
    // the original description no longer matches an edited activity
    expect(moved.notes).toBeUndefined()
    // a cleared cost falls back to the original, as on screen
    expect(p.itinerary.days[1].slots[0].estimated_cost_usd).toBe(15)
    expect(p.itinerary.days[1].slots[0].notes).toBe('About Belem')
  })

  it('keeps the original name and notes for an empty-string activity edit, as on screen', () => {
    const edits = { '1-morning': { activity: '' } }
    const p = buildStressTestPayload(SEARCH, RESULTS, selections({ itinerary_edits: edits }))
    const s = p.itinerary.days[0].slots[0]
    expect(s.activity).toBe('Castle')
    expect(s.notes).toBe('About Castle')
  })

  it('strips the client-only key from every slot', () => {
    const layout = moveSlot(ITIN, null, '1-morning', 2, 'evening')
    for (const sel of [selections(), selections({ itinerary_layout: layout })]) {
      const slots = buildStressTestPayload(SEARCH, RESULTS, sel).itinerary.days.flatMap((d) => d.slots)
      expect(slots.length).toBeGreaterThan(0)
      for (const s of slots) expect(s).not.toHaveProperty('key')
    }
  })

  it('excludes removed activities and layout bookkeeping', () => {
    const layout = removeSlot(ITIN, null, '1-afternoon')
    const p = buildStressTestPayload(SEARCH, RESULTS, selections({ itinerary_layout: layout }))
    expect(activities(p)).toEqual([['Castle', 'Fado'], ['Belem', 'LX Factory']])
    expect(JSON.stringify(p)).not.toContain('Tram 28')
    expect(p.itinerary).not.toHaveProperty('removed')
    expect(p.itinerary).not.toHaveProperty('changed')
    expect(p.itinerary.total_estimated_cost_usd).toBe(55)
  })

  it('passes flights, visa and weather without verification objects', () => {
    const p = buildStressTestPayload(SEARCH, RESULTS, selections())
    expect(p.flights).toEqual({ results: [{ price_usd: 120 }] })
    expect(p.visa).toEqual({ visa_required: false })
    expect(p.weather).toEqual({ daily: [{ date: '2027-05-01' }] })
    expect(p.itinerary).not.toHaveProperty('verification')
    expect(p).not.toHaveProperty('hotels')
    expect(p).not.toHaveProperty('stress_test')
    // inputs are not mutated
    expect(RESULTS.flights.verification).toBeDefined()
    expect(ITIN.verification).toBeDefined()
  })

  it('sends null for missing context sections', () => {
    const p = buildStressTestPayload(SEARCH, { itinerary: ITIN }, selections())
    expect(p.flights).toBeNull()
    expect(p.visa).toBeNull()
    expect(p.weather).toBeNull()
  })

  it('normalises return_date via apiReturnDate', () => {
    expect(buildStressTestPayload(SEARCH, RESULTS, selections()).return_date).toBeNull()
    expect(buildStressTestPayload({ ...SEARCH, return_date: '2027-05-03' }, RESULTS, selections()).return_date).toBe('2027-05-03')
  })
})

describe('buildStressTestPayload — times', () => {
  it('sends each slot\'s estimated start, end and travel from the previous stop', () => {
    const layout = moveSlot(ITIN, null, '1-morning', 2, 'evening')
    const p = buildStressTestPayload(SEARCH, RESULTS, selections({ itinerary_layout: layout }))
    expect(p.itinerary.days[0].slots.map((s) => [s.activity, s.start_time, s.end_time])).toEqual([
      ['Tram 28', '13:30', '15:30'], ['Fado', '18:30', '20:30'],
    ])
    expect(p.itinerary.days[1].slots[2]).toMatchObject({ activity: 'Castle', start_time: '18:30', end_time: '20:30', transit_from_prev: null })
    expect(p.itinerary.days[0]).toHaveProperty('schedule_warnings', [])
  })
})

describe('recheckFingerprint', () => {
  it('changes when the layout or an edit changes, and only then', () => {
    const layout = moveSlot(ITIN, null, '1-morning', 2, 'evening')
    const base = recheckFingerprint(RESULTS.itinerary, selections({ itinerary_layout: layout }))
    expect(recheckFingerprint(RESULTS.itinerary, selections({ itinerary_layout: layout }))).toBe(base)
    expect(recheckFingerprint(RESULTS.itinerary, selections({ itinerary_layout: removeSlot(ITIN, layout, '1-evening') }))).not.toBe(base)
    expect(recheckFingerprint(RESULTS.itinerary, selections({ itinerary_layout: layout, itinerary_edits: { '1-evening': { location: 'Bairro Alto' } } }))).not.toBe(base)
  })
})

describe('recheckErrorMessage', () => {
  it("uses the server's string detail, else a generic retry message", () => {
    expect(recheckErrorMessage({ response: { status: 429, data: { detail: 'Too many requests — wait a minute' } } })).toBe('Too many requests — wait a minute')
    expect(recheckErrorMessage({ response: { status: 422, data: { detail: [{ msg: 'bad' }] } } })).toBe("Couldn't re-check — try again")
    expect(recheckErrorMessage(new Error('Network Error'))).toBe("Couldn't re-check — try again")
    expect(recheckErrorMessage(undefined)).toBe("Couldn't re-check — try again")
  })
})

describe('buildStressTestPayload — scheduled order', () => {
  // ~8 km apart by street in Lisbon: travel between them is by transit
  const at = (lat, lng) => ({ lat, lng })
  const B = { ...slot('afternoon', 'Gulbenkian', 10), ...at(38.737, -9.154) }
  const A = { ...slot('morning', 'Oceanario', 20), ...at(38.7635, -9.0937) }
  const OUT_OF_ORDER = {
    days: [
      { day_number: 1, date: '2027-05-01', city: 'Lisbon', slots: [B, A] },
      { day_number: 2, date: '2027-05-02', city: 'Lisbon', slots: [slot('morning', 'Belem', 15), slot('afternoon', 'LX Factory', 0)] },
    ],
  }
  const results = { ...RESULTS, itinerary: OUT_OF_ORDER }

  it('lists an out-of-order day as scheduled, so travel is from the stop listed just before', () => {
    const p = buildStressTestPayload(SEARCH, results, selections())
    const [day1] = p.itinerary.days
    expect(day1.slots.map((s) => s.activity)).toEqual(['Oceanario', 'Gulbenkian'])
    expect(day1.slots[0]).toMatchObject({ start_time: '09:00', transit_from_prev: null })
    expect(day1.slots[1].transit_from_prev).toMatchObject({ mode: 'transit' })
    expect(day1.slots[1].start_time).toBe('13:30')
  })

  it('leaves days already in order unchanged', () => {
    const p = buildStressTestPayload(SEARCH, results, selections())
    expect(p.itinerary.days[1].slots.map((s) => [s.activity, s.start_time])).toEqual([['Belem', '09:00'], ['LX Factory', '13:30']])
    expect(activities(buildStressTestPayload(SEARCH, RESULTS, selections()))).toEqual([['Castle', 'Tram 28', 'Fado'], ['Belem', 'LX Factory']])
  })

  it('fingerprints the scheduled order', () => {
    const listed = recheckFingerprint(OUT_OF_ORDER, selections())
    const reordered = recheckFingerprint({ ...OUT_OF_ORDER, days: [{ ...OUT_OF_ORDER.days[0], slots: [A, B] }, OUT_OF_ORDER.days[1]] }, selections())
    expect(listed).toBe(reordered)
  })
})
