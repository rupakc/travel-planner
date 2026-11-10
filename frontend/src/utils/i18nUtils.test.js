import { describe, it, expect, afterEach } from 'vitest'
import i18n from '../i18n'
import { enumLabel } from './enumLabel'
import { relativeTime, untilTime } from './fareWatch'
import { priceCheckMessage, filterStatus } from './priceWatch'
import { getBudgetStatus } from './planHelpers'

afterEach(async () => { await i18n.changeLanguage('en') })

describe('enumLabel', () => {
  it('returns the translated word for a known value', async () => {
    await i18n.changeLanguage('de')
    expect(enumLabel('level', 'high')).toBe('hoch')
    expect(enumLabel('coverage', 'Excellent')).toBe('ausgezeichnet')
    expect(enumLabel('severity', 'warning')).toBe('Warnung')
  })

  it('returns an unknown value (or group) unchanged', async () => {
    await i18n.changeLanguage('de')
    expect(enumLabel('level', 'extreme')).toBe('extreme')
    expect(enumLabel('nope', 'high')).toBe('high')
    expect(enumLabel('level', undefined)).toBeUndefined()
  })
})

describe('relative time plurals', () => {
  const NOW = new Date('2026-11-04T12:00:00Z')

  it('uses singular and plural forms by count', () => {
    expect(untilTime('2026-11-05T12:00:00Z', NOW)).toBe('in 1 day')
    expect(untilTime('2026-11-06T12:00:00Z', NOW)).toBe('in 2 days')
    expect(relativeTime('2026-11-02T12:00:00Z', NOW)).toBe('2 days ago')
    expect(relativeTime('2026-11-03T12:00:00Z', NOW)).toBe('yesterday')
  })

  it('follows the language', async () => {
    await i18n.changeLanguage('de')
    expect(untilTime('2026-11-05T12:00:00Z', NOW)).toBe('in 1 Tag')
    expect(untilTime('2026-11-06T12:00:00Z', NOW)).toBe('in 2 Tagen')
    expect(relativeTime('2026-11-04T11:55:00Z', NOW)).toBe('vor 5 Min.')
  })
})

describe('translated util copy', () => {
  it('renders alert util text in German', async () => {
    await i18n.changeLanguage('de')
    expect(priceCheckMessage({ check_status: 'failed' }).text)
      .toBe('Die Live-Preise haben nicht geantwortet. Wir versuchen es innerhalb einer Stunde erneut.')
    expect(filterStatus('hotel', 2)).toBe('2 Hotel-Beobachtungen angezeigt')
  })

  it('formats the budget label per language', async () => {
    expect(getBudgetStatus(900, 1000).label).toBe('$100 under budget')
    await i18n.changeLanguage('de')
    expect(getBudgetStatus(1200, 1000).label).toMatch(/200.*über dem Budget/)
  })
})
