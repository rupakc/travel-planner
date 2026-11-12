// @vitest-environment node
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import {
  verdictFor, adviceFor, typicalFor, lowestOf, latestOf, countAtOrBelow, checkedDaysAgo,
} from './alertStory'

const FIXTURE = fileURLToPath(new URL('../../../backend/tests/fixtures/alerts/story_cases.json', import.meta.url))
const cases = JSON.parse(readFileSync(FIXTURE, 'utf8'))

describe('alertStory vs story_cases.json', () => {
  it('has the contract cases', () => { expect(cases.length).toBeGreaterThanOrEqual(25) })
  for (const c of cases) {
    it(c.name, () => {
      const i = c.input
      const typical = typicalFor(i)
      expect(typical).toEqual(c.expected.typical)
      const latest = latestOf(i.points)
      expect(latest).toBe(c.expected.latest)
      expect(lowestOf(i.points)).toBe(c.expected.lowest)
      const verdict = verdictFor(latest, typical, { checkedDaysAgo: i.checked_days_ago, livePrices: i.live_prices })
      expect(verdict).toBe(c.expected.verdict)
      const advice = adviceFor({ ...i, typical, verdict })
      expect(advice.code).toBe(c.expected.advice.code)
      for (const [k, v] of Object.entries(c.expected.advice.params)) expect(advice.params[k]).toBeCloseTo(v, 6)
      // Deriving the verdict inside adviceFor gives the same answer.
      expect(adviceFor({ ...i, typical }).code).toBe(c.expected.advice.code)
    })
  }
})

describe('small helpers', () => {
  it('counts points at or below a target', () => {
    expect(countAtOrBelow([{ price: 5 }, { price: 10 }, { price: 12 }], 10)).toBe(2)
    expect(countAtOrBelow([], 10)).toBe(0)
  })
  it('computes whole days since a check', () => {
    const now = Date.parse('2026-11-12T12:00:00Z')
    expect(checkedDaysAgo('2026-11-09T12:00:00Z', now)).toBe(3)
    expect(checkedDaysAgo(null, now)).toBeNull()
  })
})
