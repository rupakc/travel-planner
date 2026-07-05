// @vitest-environment node
import { describe, it, expect } from 'vitest'
import { orderSectionByCity } from './orderSectionByCity'

// Regression: a lucide-react `Map` icon import once shadowed the global Map
// inside the module hosting this function, making `new Map(...)` throw
// "not a constructor" for every multi-city section and freezing the results
// page. These tests execute the multi-city path (>= 2 destinations) so any
// future shadowing crashes the suite immediately.
describe('orderSectionByCity', () => {
  const destinations = ['Amsterdam', 'New York', 'San Francisco']

  it('does not throw and sorts city-tagged lists into journey order', () => {
    const data = {
      results: [
        { name: 'c', city: 'San Francisco' },
        { name: 'a', city: 'Amsterdam' },
        { name: 'b', city: 'New York, USA' },
      ],
    }
    const out = orderSectionByCity(data, destinations)
    expect(out.results.map(r => r.name)).toEqual(['a', 'b', 'c'])
  })

  it('is a stable sort within the same city and puts unknown cities last', () => {
    const data = {
      hotels: [
        { name: 'x', city: 'Atlantis' },
        { name: 'h1', city: 'Amsterdam' },
        { name: 'h2', city: 'Amsterdam' },
      ],
    }
    const out = orderSectionByCity(data, destinations)
    expect(out.hotels.map(h => h.name)).toEqual(['h1', 'h2', 'x'])
  })

  it('returns input untouched for single-city trips and non-object data', () => {
    const data = { results: [{ city: 'Rome' }] }
    expect(orderSectionByCity(data, ['Rome'])).toBe(data)
    expect(orderSectionByCity(null, destinations)).toBe(null)
    expect(orderSectionByCity([1, 2], destinations)).toEqual([1, 2])
  })

  it('handles array-valued city fields and missing cities without crashing', () => {
    const data = {
      places: [
        { name: 'p2', city: ['New York', 'NYC'] },
        { name: 'p3' },
        { name: 'p1', city: 'amsterdam' },
      ],
    }
    const out = orderSectionByCity(data, destinations)
    expect(out.places.map(p => p.name)).toEqual(['p1', 'p2', 'p3'])
  })
})
