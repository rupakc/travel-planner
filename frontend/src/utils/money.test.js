import { describe, it, expect } from 'vitest'
import { currencyExponent, toAmountString } from './money'

describe('currencyExponent', () => {
  it('follows the contract table', () => {
    expect(currencyExponent('JPY')).toBe(0)
    expect(currencyExponent('kwd')).toBe(3)
    expect(currencyExponent('EUR')).toBe(2)
  })
})

describe('toAmountString', () => {
  it('accepts a locale comma decimal', () => {
    expect(toAmountString('12,50', 'EUR')).toBe('12.50')
  })
  it('reads thousands separators', () => {
    expect(toAmountString('1,234.50', 'USD')).toBe('1234.50')
    expect(toAmountString('1.234,50', 'EUR')).toBe('1234.50')
  })
  it('rejects more decimals than the currency allows', () => {
    expect(toAmountString('12.5', 'JPY')).toBeNull()
    expect(toAmountString('12.345', 'EUR')).toBeNull()
    expect(toAmountString('12.345', 'KWD')).toBe('12.345')
    expect(toAmountString('1200', 'JPY')).toBe('1200')
  })
  it('rejects empty, zero, negative, junk and over-limit values', () => {
    for (const v of ['', '0', '0,00', '-5', 'abc', '1e3', '1,2,3', '1000000.01', null]) {
      expect(toAmountString(v, 'USD')).toBeNull()
    }
    expect(toAmountString('1000000', 'USD')).toBe('1000000')
  })
})
