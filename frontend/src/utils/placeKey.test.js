// @vitest-environment node
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { placeKey } from './placeKey'

const FIXTURE = fileURLToPath(new URL('../../../backend/tests/fixtures/journey/place_key_cases.json', import.meta.url))
const { cases } = JSON.parse(readFileSync(FIXTURE, 'utf8'))

const SERVER_RE = /^[a-z]+:[a-z0-9-]{1,60}$/

describe('placeKey', () => {
  it('has the contract vectors', () => {
    expect(cases.length).toBeGreaterThanOrEqual(12)
    expect(cases.some((c) => c.name.length === 100)).toBe(true)
  })

  for (const c of cases) {
    it(`${c.note}: ${JSON.stringify(c.name).slice(0, 40)}`, () => {
      const key = placeKey(c.kind, c.name)
      expect(key).toBe(c.key)
      expect(key).toMatch(SERVER_RE)
    })
  }

  it('gives distinct non-Latin names distinct valid keys', () => {
    const a = placeKey('nearby', '京都駅')
    const b = placeKey('nearby', '東京タワー')
    expect(a).not.toBe(b)
    expect(a).toMatch(/^nearby:x-[0-9a-f]{8}$/)
    expect(placeKey('nearby', '京都駅')).toBe(a)
    expect(placeKey('nearby', ' 京都駅 ')).toBe(a)
    expect(placeKey('nearby', 'ताज महल')).toMatch(SERVER_RE)
  })

  it('treats a missing name as empty', () => {
    expect(placeKey('place', null)).toBe('place:x')
    expect(placeKey('place', undefined)).toBe('place:x')
  })
})
