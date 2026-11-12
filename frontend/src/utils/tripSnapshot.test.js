import { describe, it, expect } from 'vitest'
import { snapshotFromResults, searchMatchesPlan, hasSnapshotData } from './tripSnapshot'

describe('snapshotFromResults', () => {
  it('drops error sections and verification', () => {
    const snap = snapshotFromResults({
      emergency_card: { police: '110', verification: { level: 'verified' } },
      forex: { error: 'boom' },
      visa: { required: true },
    })
    expect(snap).toEqual({ emergency_card: { police: '110' }, forex: null, visa: { required: true }, packing_list: null, weather: null })
  })
  it('handles missing results', () => {
    expect(snapshotFromResults(undefined).weather).toBeNull()
  })
})

describe('searchMatchesPlan / hasSnapshotData', () => {
  const plan = { search_data: { destination: 'Lisbon', departure_date: '2027-04-01' } }
  it('matches on destination and departure', () => {
    expect(searchMatchesPlan({ destination: 'lisbon ', departure_date: '2027-04-01' }, plan)).toBe(true)
    expect(searchMatchesPlan({ destination: 'Porto', departure_date: '2027-04-01' }, plan)).toBe(false)
    expect(searchMatchesPlan(null, plan)).toBe(false)
  })
  it('detects an all-null snapshot', () => {
    expect(hasSnapshotData(snapshotFromResults({}))).toBe(false)
    expect(hasSnapshotData(snapshotFromResults({ visa: { a: 1 } }))).toBe(true)
  })
})
