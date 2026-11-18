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

  it.each([
    ['  JaVaScRiPt:alert(1)', 'JaVaScRiPt:alert(1)'],
    ['data:text/html,<script>alert(1)</script>', 'data:text/html,&lt;script&gt;alert(1)&lt;/script&gt;'],
    ['vbscript:msgbox(1)', 'vbscript:msgbox(1)'],
  ])('does not link website %j and shows it escaped', (website, shown) => {
    const html = buildEmergencyCardHtml({ data: { embassy: { name: 'E', website } }, destination: 'X' })
    expect(html).not.toMatch(/href="\s*(javascript|data:|vbscript)/i)
    expect(html).not.toContain('<script>alert(1)')
    expect(html).toContain(shown)
  })

  it('does not put a breakout phone into a tel: href', () => {
    const phone = '+1" onclick="alert(1)'
    const html = buildEmergencyCardHtml({ data: { embassy: { name: 'E', phone }, hospitals: [{ name: 'H', phone }] }, destination: 'X' })
    expect(html).not.toContain('tel:')
    expect(html).not.toMatch(/"\s*onclick="/)
    expect(html).toContain('+1&quot; onclick=&quot;alert(1)')
  })

  it('escapes text injection in a single (non multi-city) card', () => {
    const html = buildEmergencyCardHtml({ data: { embassy: { name: XSS } }, destination: 'X' })
    expect(html).not.toContain('<script>alert(1)')
    expect(html).toContain('<strong>&lt;script&gt;alert(1)&lt;/script&gt;</strong>')
  })
})

describe('buildEmergencyCardHtml with phones removed as unverified (crawler data)', () => {
  const LABEL = 'Phone number not verified — check the official website.'
  const removed = {
    emergency_numbers: { police: '110' },
    embassy: { name: 'Embassy of X', address: 'Addr', phone: null, emergency_after_hours: null, phone_unverified: true, website: 'https://embassy.test', hours: '9-5' },
    hospitals: [{ name: 'Hospital H', phone: null, phone_unverified: true, address: 'Street 1' }],
    medical_facilities: [{ name: 'Official clinic', source: { url: 'https://www.gov.uk/medical-list' } }],
  }
  const count = (html) => html.split(LABEL).length - 1

  it('labels the removed embassy and hospital phones instead of a blank', () => {
    const html = buildEmergencyCardHtml({ data: removed, destination: 'X' })
    expect(count(html)).toBe(2)
    expect(html).not.toMatch(/📞\s*(\||<br|<\/p>)/)
    expect(html).not.toContain('After hours: —')
  })

  it('links the hospital label to the official medical list, never javascript:', () => {
    const html = buildEmergencyCardHtml({ data: removed, destination: 'X' })
    expect(html).toContain(`<a href="https://www.gov.uk/medical-list">${LABEL}</a>`)
    const bad = buildEmergencyCardHtml({ data: { ...removed, medical_facilities: [{ source: { url: 'javascript:alert(1)' } }] }, destination: 'X' })
    expect(bad).not.toMatch(/href="javascript/i)
    expect(count(bad)).toBe(2)
  })

  it('never prints a guessed number when the phone is flagged unverified', () => {
    const html = buildEmergencyCardHtml({
      data: { cities: [{ ...removed, city: 'Paris', embassy: { ...removed.embassy, phone: '+33 1 0000' }, hospitals: [{ name: 'H', phone: '+33 2 0000', phone_unverified: true }] }] },
      destination: 'X',
    })
    expect(html).not.toContain('+33')
    expect(count(html)).toBe(2)
  })

  it('is unchanged when the flags are absent (crawler off)', () => {
    const html = buildEmergencyCardHtml({ data: { embassy: { name: 'E', phone: '+1 555', emergency_after_hours: '+1 666' }, hospitals: [{ name: 'H', phone: '+1 777' }] }, destination: 'X' })
    expect(html).not.toContain(LABEL)
    expect(html).toContain('📞 <a href="tel:+1 555">+1 555</a>')
    expect(html).toContain('+1 666')
    expect(html).toContain('📞 <a href="tel:+1 777">+1 777</a>')
  })
})
