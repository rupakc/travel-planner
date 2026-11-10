import { describe, it, expect, afterEach } from 'vitest'
import i18n from 'i18next'
import { fmtCurrency, fmtNumber, fmtDate, fmtRelative, intlLocale } from './format'

afterEach(async () => { await i18n.changeLanguage('en') })

describe('format', () => {
  it('maps app languages to Intl locales', () => {
    expect(intlLocale('zh')).toBe('zh-CN')
    expect(intlLocale('hi')).toBe('hi-IN')
    expect(intlLocale('bn')).toBe('bn-IN')
    expect(intlLocale('de')).toBe('de')
  })

  it('formats currency the German way in de', async () => {
    await i18n.changeLanguage('de')
    expect(fmtCurrency(1234.5, 'EUR')).toContain('1.234,50')
  })

  it('uses Indian digit grouping in hi', async () => {
    await i18n.changeLanguage('hi')
    expect(fmtNumber(1234567)).toBe('12,34,567')
  })

  it('formats in English by default', () => {
    expect(fmtNumber(1234.5)).toBe('1,234.5')
    expect(fmtCurrency(12, 'USD')).toBe('$12.00')
    expect(fmtDate(new Date(Date.UTC(2026, 3, 1, 12)), { dateStyle: 'medium', timeZone: 'UTC' })).toBe('Apr 1, 2026')
    expect(fmtDate('2026-04-01T12:00:00Z', { month: 'long', timeZone: 'UTC' })).toBe('April')
  })

  it('formats relative time from a signed offset in ms', async () => {
    expect(fmtRelative(-3 * 60 * 60 * 1000)).toBe('3 hours ago')
    expect(fmtRelative(2 * 24 * 60 * 60 * 1000)).toBe('in 2 days')
    expect(fmtRelative(-10 * 1000)).toBe('now')
    await i18n.changeLanguage('de')
    expect(fmtRelative(-24 * 60 * 60 * 1000)).toBe('gestern')
  })

  it('never throws on bad input', () => {
    expect(fmtCurrency(5, 'not a code')).toBe('5')
    expect(fmtDate('garbage')).toBe('')
  })
})

describe('missing translations', () => {
  it('a key missing in de renders the English text, never the raw key', async () => {
    i18n.addResource('en', 'common', 'test.onlyInEnglish', 'Only in English')
    await i18n.changeLanguage('de')
    expect(i18n.language).toBe('de')
    expect(i18n.t('common:test.onlyInEnglish')).toBe('Only in English')
    expect(i18n.t('common:nav.search')).toBe('Suche')
  })
})
