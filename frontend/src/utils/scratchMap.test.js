import { describe, it, expect } from 'vitest'
import { project, decodeCountries, countryPath, visitedSet, regionName, MAP_WIDTH, MAP_HEIGHT } from './scratchMap'
import data from '../assets/worldCountries.json'

describe('scratchMap', () => {
  it('projects corners and the origin', () => {
    expect(project(-180, 84)).toEqual([0, 0])
    expect(project(180, -58)).toEqual([MAP_WIDTH, MAP_HEIGHT])
    expect(project(0, 84 - (142 / 2))[0]).toBe(MAP_WIDTH / 2)
  })
  it('clamps latitude', () => {
    expect(project(0, -90)[1]).toBe(MAP_HEIGHT)
  })
  it('decodes delta-encoded rings', () => {
    const out = decodeCountries({ s: 10, f: [['XX', [[100, 200, 10, -10, -10, 0]]]] })
    expect(out[0].rings[0]).toEqual([[10, 20], [11, 19], [10, 19]])
  })
  it('builds a closed path per ring', () => {
    const d = countryPath([[[-180, 84], [180, 84], [180, -58]]])
    expect(d).toBe(`M0 0L${MAP_WIDTH} 0L${MAP_WIDTH} ${MAP_HEIGHT}Z`)
  })
  it('bundled dataset has ISO2 codes and plausible coordinates', () => {
    const all = decodeCountries(data)
    expect(all.length).toBeGreaterThan(150)
    const fr = all.find((c) => c.code === 'FR')
    expect(fr).toBeTruthy()
    for (const [lon, lat] of fr.rings.flat()) {
      expect(lon).toBeGreaterThan(-180); expect(lon).toBeLessThan(180)
      expect(lat).toBeGreaterThan(-90); expect(lat).toBeLessThan(90)
    }
    expect(all.every((c) => /^[A-Z]{2}$/.test(c.code))).toBe(true)
  })
  it('visitedSet normalises and ignores junk', () => {
    const s = visitedSet([{ code: 'fr' }, 'jp', { code: 'ZZZ' }, null, {}])
    expect([...s].sort()).toEqual(['FR', 'JP'])
    expect(visitedSet(undefined).size).toBe(0)
  })
  it('regionName localises and falls back to the code', () => {
    expect(regionName('DE', 'en')).toBe('Germany')
    expect(regionName('??', 'en')).toBe('??')
  })
})
