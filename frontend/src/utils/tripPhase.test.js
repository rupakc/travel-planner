import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'
import { effectivePhase, dayIndex, daysToStart, localToday } from './tripPhase'

const here = dirname(fileURLToPath(import.meta.url))
const cases = JSON.parse(
  readFileSync(
    resolve(here, '../../../backend/tests/fixtures/journey/trip_phase_cases.json'),
    'utf8',
  ),
)

describe('golden trip phase cases', () => {
  it('has at least 20 cases', () => {
    expect(cases.length).toBeGreaterThanOrEqual(20)
  })
  for (const c of cases) {
    it(c.name, () => {
      expect(
        effectivePhase({
          start: c.start,
          end: c.end,
          override: c.override,
          today: c.today,
          prepComplete: c.prep_complete,
        }),
      ).toBe(c.phase)
      expect(dayIndex(c.start, c.end, c.today)).toBe(c.day_index)
      expect(daysToStart(c.start, c.today)).toBe(c.days_to_start)
    })
  }
})

describe('localToday', () => {
  it('uses the local calendar date', () => {
    expect(localToday(new Date(2026, 10, 13, 7, 0))).toBe('2026-11-13')
    expect(localToday(new Date(2026, 0, 5, 23, 59))).toBe('2026-01-05')
  })
})
