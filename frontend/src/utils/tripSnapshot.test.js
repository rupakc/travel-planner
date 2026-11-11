import { describe, it, expect } from 'vitest'
import { snapshotFromResults } from './tripSnapshot'

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
