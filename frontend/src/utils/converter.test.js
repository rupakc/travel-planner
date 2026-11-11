import { describe, it, expect } from 'vitest'
import { convert, roundFor } from './converter'

describe('converter', () => {
  it('converts both ways', () => {
    expect(convert(100, 0.92, 'toLocal')).toBeCloseTo(92)
    expect(convert(92, 0.92, 'toHome')).toBeCloseTo(100)
  })
  it('rounds JPY to whole yen, KWD to 3 places, others to 2', () => {
    expect(roundFor('JPY', 15234.6)).toBe(15235)
    expect(roundFor('KWD', 1.23456)).toBe(1.235)
    expect(roundFor('EUR', 12.345)).toBeCloseTo(12.35)
  })
  it('gives NaN for a bad amount or rate', () => {
    expect(convert('x', 1, 'toLocal')).toBeNaN()
    expect(convert(5, 0, 'toHome')).toBeNaN()
    expect(convert(5, null, 'toLocal')).toBeNaN()
  })
})
