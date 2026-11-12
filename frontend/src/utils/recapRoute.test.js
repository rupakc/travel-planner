import { describe, it, expect } from 'vitest'
import { plannedRoute } from './recapRoute'

describe('plannedRoute', () => {
  it('skips slots without coordinates and sums the distance', () => {
    const days = [
      { slots: [{ lat: 38.7, lng: -9.14 }, { name: 'no coords' }, { lat: null, lng: 3 }] },
      { slots: [{ lat: 38.75, lng: -9.2 }] },
    ]
    const r = plannedRoute(days)
    expect(r.points).toEqual([[38.7, -9.14], [38.75, -9.2]])
    expect(r.km).toBeGreaterThan(5)
    expect(r.km).toBeLessThan(10)
  })
  it('gives km null with one point or none', () => {
    expect(plannedRoute([{ slots: [{ lat: 1, lng: 2 }] }])).toEqual({ points: [[1, 2]], km: null })
    expect(plannedRoute(undefined)).toEqual({ points: [], km: null })
    expect(plannedRoute([{ slots: [{ lat: 99, lng: 2 }] }]).points).toEqual([])
  })
})
