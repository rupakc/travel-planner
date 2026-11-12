// @vitest-environment node
import { describe, it, expect } from 'vitest'
import { directionsUrl, isApplePlatform } from './mapsLinks'

describe('directionsUrl', () => {
  const p = { lat: 38.7, lng: -9.1, name: 'Belém Tower' }
  it('builds Google and Apple walking links', () => {
    expect(directionsUrl(p, { apple: false })).toBe('https://www.google.com/maps/dir/?api=1&destination=38.7,-9.1&travelmode=walking')
    expect(directionsUrl(p, { apple: true })).toBe('https://maps.apple.com/?daddr=38.7,-9.1&dirflg=w')
  })
  it('falls back to the encoded name without coordinates', () => {
    expect(directionsUrl({ name: 'Belém Tower' }, {})).toContain('destination=Bel%C3%A9m%20Tower')
    expect(directionsUrl({ name: 'A&B' }, { apple: true })).toBe('https://maps.apple.com/?daddr=A%26B&dirflg=w')
  })
  it('detects iOS and iPadOS user agents', () => {
    expect(isApplePlatform({ userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0)' })).toBe(true)
    expect(isApplePlatform({ userAgent: 'Mozilla/5.0 (Macintosh)', maxTouchPoints: 5 })).toBe(true)
    expect(isApplePlatform({ userAgent: 'Mozilla/5.0 (Macintosh)', maxTouchPoints: 0 })).toBe(false)
    expect(isApplePlatform({ userAgent: 'Android' })).toBe(false)
  })
})
