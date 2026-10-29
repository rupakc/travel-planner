// @vitest-environment node
import { describe, it, expect } from 'vitest'
import { haversineKm } from './geo'

describe('haversineKm', () => {
  it('is zero for the same point', () => {
    expect(haversineKm(35.68, 139.76, 35.68, 139.76)).toBe(0)
  })

  it('measures great-circle distance in km', () => {
    // London -> Paris is ~344 km
    expect(haversineKm(51.5074, -0.1278, 48.8566, 2.3522)).toBeCloseTo(343.5, 0)
    // one degree of latitude is ~111.2 km
    expect(haversineKm(0, 0, 1, 0)).toBeCloseTo(111.19, 1)
  })
})
