// @vitest-environment node
import { describe, it, expect } from 'vitest'
import { clearPendingVerification, stripLinkEvidence } from './verification'

describe('clearPendingVerification', () => {
  it('clears pending on sections still pending, copying not mutating', () => {
    const pendingV = { level: 'unverified', summary: 'Checking which links can be found online…', pending: true }
    const doneV = { level: 'verified', pending: false }
    const results = {
      hotels: { results: [{ name: 'A' }], verification: pendingV },
      flights: { results: [], verification: doneV },
      visa: { requirement: {} },
      itinerary: null,
    }
    const out = clearPendingVerification(results)
    expect(out).not.toBe(results)
    expect(out.hotels).not.toBe(results.hotels)
    expect(out.hotels.verification.pending).toBe(false)
    expect(out.hotels.verification.summary).not.toMatch(/Checking/)
    expect(out.hotels.results).toBe(results.hotels.results)
    expect(results.hotels.verification.pending).toBe(true)
    expect(pendingV.pending).toBe(true)
    expect(out.flights).toBe(results.flights)
    expect(out.visa).toBe(results.visa)
    expect(out.itinerary).toBeNull()
  })

  it('returns the same object when nothing is pending', () => {
    const results = { flights: { verification: { pending: false } } }
    expect(clearPendingVerification(results)).toBe(results)
    expect(clearPendingVerification(null)).toBeNull()
  })
})

describe('stripLinkEvidence', () => {
  it('drops link_verified / link_checked from saved items without mutating', () => {
    const act = { name: 'Tour', link_verified: true, link_checked: true, booking_url: 'https://x' }
    const hotel = { name: 'H', link_verified: false }
    const plain = { name: 'Plain' }
    const selections = {
      hotel,
      activities: [act, plain],
      places_to_see: [],
      itinerary_notes: { a: 'note' },
      flight: null,
    }
    const out = stripLinkEvidence(selections)
    expect(out.activities[0]).toEqual({ name: 'Tour', booking_url: 'https://x' })
    expect(out.activities[1]).toBe(plain)
    expect(out.hotel).toEqual({ name: 'H' })
    expect(out.itinerary_notes).toBe(selections.itinerary_notes)
    expect(out.flight).toBeNull()
    expect(act.link_verified).toBe(true)
    expect(act.link_checked).toBe(true)
    expect(hotel.link_verified).toBe(false)
    expect(selections.activities[0]).toBe(act)
  })
})
