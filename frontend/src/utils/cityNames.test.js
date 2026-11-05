import { describe, it, expect } from 'vitest'
import { cityForCode, isAirportCode, withCityNames } from './cityNames'

const names = { LIS: 'Lisbon', CDG: 'Paris' }
const name = (v) => (isAirportCode(v) && names[String(v).trim()]) || v

describe('cityNames', () => {
  it('tells an ALL-CAPS airport code from a city name', () => {
    expect(isAirportCode('LIS')).toBe(true)
    expect(isAirportCode(' LIS ')).toBe(true)
    for (const v of ['Lisbon', 'Goa', 'lis', 'Lisbon, Portugal', '', null, undefined]) {
      expect(isAirportCode(v)).toBe(false)
    }
  })

  it('names the destination and every multi-city leg', () => {
    const sd = { destination: 'LIS', destinations: ['CDG', 'Rome', 'LIS'], num_travelers: 2 }
    expect(withCityNames(sd, name)).toEqual({ destination: 'Lisbon', destinations: ['Paris', 'Rome', 'Lisbon'], num_travelers: 2 })
    expect(sd.destination).toBe('LIS') // not mutated
  })

  it('passes real city names (and unknown codes) through unchanged', () => {
    const sd = { destination: 'Lisbon, Portugal' }
    expect(withCityNames(sd, name)).toEqual(sd)
    expect(withCityNames({ destination: 'QQQ' }, name)).toEqual({ destination: 'QQQ' })
    expect(withCityNames(null, name)).toBeNull()
  })

  it('reads the city for a code from the airport search rows', () => {
    const rows = [
      { iata_code: 'YIW', city: 'Yiwu' },
      { iata_code: 'LIS', city: 'Lisbon', country: 'Portugal' },
    ]
    expect(cityForCode('LIS', rows)).toBe('Lisbon')
    expect(cityForCode('QQQ', rows)).toBeNull()
    expect(cityForCode('LIS', null)).toBeNull()
  })
})
