// @vitest-environment node
import { describe, it, expect } from 'vitest'
import { tripPath, TRIP_TABS, matchTripPath } from './paths'

describe('journey paths', () => {
  it('builds trip paths', () => {
    expect(tripPath(12)).toBe('/trips/12')
    expect(tripPath(12, 'today')).toBe('/trips/12/today')
    expect(TRIP_TABS).toEqual(['overview', 'prep', 'today', 'money', 'journal', 'recap', 'offline'])
  })
  it('matches only numeric ids and known tabs', () => {
    expect(matchTripPath('/trips/3')).toEqual({ id: 3, tab: null })
    expect(matchTripPath('/trips/3/today')).toEqual({ id: 3, tab: 'today' })
    expect(matchTripPath('/trips/3/today/')).toEqual({ id: 3, tab: 'today' })
    expect(matchTripPath('/trips/abc')).toBeNull()
    expect(matchTripPath('/trips/3/bogus')).toBeNull()
    expect(matchTripPath('/trips')).toBeNull()
  })
})
