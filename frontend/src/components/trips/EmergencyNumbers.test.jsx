// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import '../../i18n'
import EmergencyNumbers from './EmergencyNumbers'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
const LABEL = 'Phone number not verified — check the official website.'

let container, root
beforeEach(() => {
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})
afterEach(() => {
  act(() => root.unmount())
  container.remove()
})
const render = (emergency) => act(() => { root.render(<EmergencyNumbers emergency={emergency} />) })
const city = (over) => ({ city: 'Lisbon', emergency_numbers: { police: '112' }, local_phrases: [], ...over })
const labels = () => container.querySelectorAll('[data-testid="offline-phone-unverified"]')

describe('EmergencyNumbers (offline pack)', () => {
  it('labels removed embassy and hospital phones, linking the official sites', () => {
    render({ source: 'ai', as_of: null, cities: [city({
      embassy: { name: 'Embassy', phone: null, phone_unverified: true, website: 'https://embassy.test' },
      hospitals: [{ name: 'Hospital', phone: null, phone_unverified: true }],
      medical_list_url: 'https://www.gov.uk/list',
    })] })
    expect(labels()).toHaveLength(2)
    labels().forEach((l) => expect(l.textContent).toContain(LABEL))
    expect(container.querySelector('[data-tid="offlinePack.emergency.embassy.official"]').getAttribute('href')).toBe('https://embassy.test')
    expect(container.querySelector('[data-tid="offlinePack.emergency.hospital.official"]').getAttribute('href')).toBe('https://www.gov.uk/list')
    expect(container.querySelector('[data-tid="offlinePack.emergency.embassy"]')).toBeNull()
  })

  it('never shows a guessed number or a javascript: link when flagged', () => {
    render({ source: 'ai', as_of: null, cities: [city({
      embassy: { name: 'Embassy', phone: '+351 999', phone_unverified: true, website: 'javascript:alert(1)' },
      hospitals: [{ name: 'Hospital', phone: '+351 888', phone_unverified: true }],
    })] })
    expect(container.textContent).not.toContain('+351')
    expect(container.querySelector('a[href^="javascript"]')).toBeNull()
    expect(labels()).toHaveLength(2)
  })

  it('is unchanged without the flag (crawler off)', () => {
    render({ source: 'ai', as_of: null, cities: [city({
      embassy: { name: 'Embassy', phone: '+351 999' },
      hospitals: [{ name: 'Hospital', phone: '+351 888' }],
    })] })
    expect(container.textContent).not.toContain(LABEL)
    expect(container.querySelector('[data-tid="offlinePack.emergency.embassy"]').getAttribute('href')).toBe('tel:+351999')
    expect(container.querySelector('[data-tid="offlinePack.emergency.hospital"]').getAttribute('href')).toBe('tel:+351888')
  })
})
