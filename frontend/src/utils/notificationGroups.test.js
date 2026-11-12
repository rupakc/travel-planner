import { describe, it, expect } from 'vitest'
import { groupDrops } from './notificationGroups'

const at = (min) => new Date(Date.UTC(2026, 10, 12, 12, 0) - min * 60000).toISOString()
const drop = (id, min, kind = 'fare_drop') => ({ id, kind, created_at: at(min), data: { drop: { observed: true } } })

describe('groupDrops', () => {
  it('merges within the window only', () => {
    const list = [drop(5, 0), drop(4, 5), drop(3, 12), drop(2, 60), drop(1, 70)]
    const g = groupDrops(list, 15)
    expect(g.map((x) => x.ids)).toEqual([[5, 4, 3], [2, 1]])
    expect(g[0].count).toBe(3)
    expect(g[0].latest.id).toBe(5)
    expect(g[1].count).toBe(2)
  })

  it('keeps kinds, non-drops and a zero window apart', () => {
    const list = [drop(4, 0), drop(3, 1, 'hotel_drop'), { id: 2, kind: 'price_digest', created_at: at(2) }, drop(1, 3)]
    const g = groupDrops(list, 15)
    expect(g.map((x) => x.ids)).toEqual([[4, 1], [3], [2]])
    expect(groupDrops(list, 0).every((x) => x.count === 1)).toBe(true)
  })

  it('never merges an unobserved drop and handles empty input', () => {
    const est = { id: 9, kind: 'fare_drop', created_at: at(1), data: { drop: { observed: false } } }
    expect(groupDrops([drop(8, 0), est], 15).map((x) => x.ids)).toEqual([[8], [9]])
    expect(groupDrops(null, 15)).toEqual([])
  })
})
