import { describe, it, expect } from 'vitest'
import { langAttr, quotedValue } from './placeFactText'

describe('place fact language tags', () => {
  it('keeps real tags and drops und, junk and absence', () => {
    expect(langAttr('de')).toBe('de')
    expect(langAttr('zh-Hant')).toBe('zh-Hant')
    for (const t of ['und', 'UND', '', 'd e', '<x>', 7, null, undefined, 'x'.repeat(40)]) expect(langAttr(t)).toBeNull()
  })

  it('splits the one quoted value', () => {
    expect(quotedValue('Berlin’s motto is “Berlin bleibt doch Berlin”.', 'de')).toEqual({
      before: 'Berlin’s motto is “', value: 'Berlin bleibt doch Berlin', after: '”.', lang: 'de',
    })
  })

  it('marks nothing without a value language or a single quoted value', () => {
    expect(quotedValue('Motto “A”.', undefined)).toBeNull()
    expect(quotedValue('Motto “A”.', 'und')).toBeNull()
    expect(quotedValue('No quotes here.', 'de')).toBeNull()
    expect(quotedValue('“A” and “B”.', 'de')).toBeNull()
    expect(quotedValue('Open “only.', 'de')).toBeNull()
    expect(quotedValue('Empty “ ”.', 'de')).toBeNull()
  })
})
