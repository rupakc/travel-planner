import { describe, it, expect } from 'vitest'
import { buildEmergencyCardHtml, telHref } from './emergencyCardPrint'

const XSS = '<script>alert(1)</script>'
const ATTR = '" onmouseover="alert(1)'

describe('buildEmergencyCardHtml', () => {
  const card = {
    emergency_numbers: { police: XSS, ambulance: '112' },
    embassy: { name: XSS, address: ATTR, phone: '+1 555-0100', website: `https://x.test/"${ATTR}`, hours: '9-5' },
    hospitals: [{ name: XSS, phone: ATTR, address: XSS, notes: XSS }],
    local_phrases: [{ english: XSS, local: XSS, phonetic: XSS }],
    local_laws: [{ law: XSS, detail: XSS, severity: 'critical' }],
  }

  it('escapes script payloads in every field', () => {
    const html = buildEmergencyCardHtml({ data: { cities: [{ ...card, city: XSS }] }, destination: XSS })
    expect(html).not.toContain('<script>alert(1)')
    expect(html).toContain('&lt;script&gt;alert(1)&lt;/script&gt;')
  })

  it('never lets an attribute payload break out of a quote', () => {
    const html = buildEmergencyCardHtml({ data: card, destination: 'X' })
    expect(html).not.toMatch(/"\s*onmouseover="/)
    expect(html).toContain('&quot; onmouseover=&quot;')
  })

  it('does not link javascript: urls but links https ones', () => {
    const bad = buildEmergencyCardHtml({ data: { embassy: { ...card.embassy, website: 'javascript:alert(1)' } }, destination: 'X' })
    expect(bad).not.toMatch(/href="javascript/i)
    expect(bad).toContain('javascript:alert(1)')
    const ok = buildEmergencyCardHtml({ data: { embassy: { ...card.embassy, website: 'https://embassy.test/a' } }, destination: 'X' })
    expect(ok).toContain('<a href="https://embassy.test/a">')
  })

  it('telHref allows only digits, plus, spaces and dashes', () => {
    expect(telHref('+1 555-0100')).toBe('tel:+1 555-0100')
    expect(telHref('javascript:alert(1)')).toBeNull()
  })
})
