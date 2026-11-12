// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { readFileSync } from 'node:fs'

vi.mock('../telemetry/client', () => ({ emit: vi.fn() }))

import i18n from 'i18next'
import '../i18n'
import { _resetConsentForTests, getConsent, telemetryAllowed } from '../telemetry/consent'
import ConsentPrompt, { PrivacySwitch } from './ConsentPrompt'
import AttributionFooter from './ui/AttributionFooter'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
let container, root

const zone = (tz) => vi.spyOn(Intl.DateTimeFormat.prototype, 'resolvedOptions')
  .mockReturnValue({ timeZone: tz, locale: 'en' })
const mount = async (el) => {
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  await act(async () => root.render(el))
}
const tid = (id) => container.querySelector(`[data-tid="${id}"]`)

beforeEach(async () => { await i18n.changeLanguage('en') })
afterEach(() => {
  act(() => root.unmount()); container.remove()
  vi.restoreAllMocks()
  try { localStorage.clear() } catch { /* ignore */ }
  _resetConsentForTests()
})

describe('ConsentPrompt', () => {
  it('is shown for a European timezone, without blocking the page', async () => {
    zone('Europe/Paris')
    await mount(<ConsentPrompt />)
    expect(tid('privacy.allow')).not.toBeNull()
    expect(tid('privacy.deny')).not.toBeNull()
    expect(container.querySelector('[role="dialog"]')).toBeNull()
    expect(container.querySelector('[aria-modal]')).toBeNull()
  })

  it('is not shown elsewhere', async () => {
    zone('America/New_York')
    await mount(<ConsentPrompt />)
    expect(tid('privacy.allow')).toBeNull()
  })

  it('records the choice and is never shown again', async () => {
    zone('Europe/Paris')
    await mount(<ConsentPrompt />)
    await act(async () => tid('privacy.deny').click())
    expect(getConsent()).toBe('denied')
    expect(tid('privacy.deny')).toBeNull()
    act(() => root.unmount()); container.remove()
    await mount(<ConsentPrompt />)
    expect(tid('privacy.allow')).toBeNull()
  })

  it('Allow grants consent', async () => {
    zone('Europe/Paris')
    await mount(<ConsentPrompt />)
    await act(async () => tid('privacy.allow').click())
    expect(getConsent()).toBe('granted')
    expect(telemetryAllowed()).toBe(true)
  })
})

describe('PrivacySwitch', () => {
  it('flips telemetryAllowed()', async () => {
    zone('America/New_York')
    await mount(<PrivacySwitch />)
    const sw = tid('privacy.switch')
    expect(sw.getAttribute('aria-checked')).toBe('true')
    await act(async () => sw.click())
    expect(telemetryAllowed()).toBe(false)
    expect(sw.getAttribute('aria-checked')).toBe('false')
    await act(async () => sw.click())
    expect(telemetryAllowed()).toBe(true)
  })

  it('starts off for a European timezone until chosen, and links the policy', async () => {
    zone('Europe/Berlin')
    await mount(<PrivacySwitch />)
    expect(tid('privacy.switch').getAttribute('aria-checked')).toBe('false')
    expect(tid('privacy.policy').getAttribute('href')).toContain('docs/Privacy.md')
  })

  it('closes an open prompt when the switch changes the choice', async () => {
    zone('Europe/Paris')
    await mount(<><ConsentPrompt /><PrivacySwitch /></>)
    await act(async () => tid('privacy.switch').click())
    expect(tid('privacy.allow')).toBeNull()
  })
})

describe('Privacy choices (footer)', () => {
  const page = () => mount(<><AttributionFooter /><ConsentPrompt /></>)

  it('reopens the sheet for a visitor outside the EU, showing the current choice', async () => {
    zone('America/New_York')
    await page()
    expect(tid('privacy.allow')).toBeNull()
    const link = tid('privacy.choices')
    expect(link.tagName).toBe('BUTTON')
    expect(link.textContent).toBe('Privacy choices')
    await act(async () => link.click())
    expect(tid('privacy.prompt')).not.toBeNull()
    expect(tid('privacy.allow').getAttribute('aria-pressed')).toBe('true')
    expect(tid('privacy.deny').getAttribute('aria-pressed')).toBe('false')
  })

  it('"No thanks" there switches telemetry off and closes the sheet', async () => {
    zone('America/New_York')
    await page()
    expect(telemetryAllowed()).toBe(true)
    await act(async () => tid('privacy.choices').click())
    await act(async () => tid('privacy.deny').click())
    expect(telemetryAllowed()).toBe(false)
    expect(getConsent()).toBe('denied')
    expect(tid('privacy.prompt')).toBeNull()
    await act(async () => tid('privacy.choices').click())
    expect(tid('privacy.deny').getAttribute('aria-pressed')).toBe('true')
  })

  it('reopens after an EU choice, and can be closed without changing it', async () => {
    zone('Europe/Paris')
    await page()
    await act(async () => tid('privacy.allow').click())
    expect(tid('privacy.prompt')).toBeNull()
    await act(async () => tid('privacy.choices').click())
    expect(tid('privacy.allow').getAttribute('aria-pressed')).toBe('true')
    await act(async () => tid('privacy.close').click())
    expect(tid('privacy.prompt')).toBeNull()
    expect(getConsent()).toBe('granted')
  })

  it('is translated', async () => {
    zone('America/New_York')
    await i18n.changeLanguage('de')
    await page()
    expect(tid('privacy.choices').textContent).toBe('Datenschutz-Einstellungen')
  })
})

describe('overlay stacking', () => {
  it('keeps the consent banner below the tour, game toasts and alert toasts', () => {
    const z = (file, re) => Number(re.exec(readFileSync(new URL(file, import.meta.url), 'utf8'))[1])
    const banner = z('./ConsentPrompt.jsx', /fixed bottom-3[^"]*z-(?:\[)?(\d+)/)
    expect(banner).toBeLessThan(z('./OnboardingTour.jsx', /fixed inset-0 z-\[(\d+)\]/))
    expect(banner).toBeLessThan(z('./game/GameCelebration.jsx', /fixed bottom-4 left-4 z-\[?(\d+)/))
    expect(banner).toBeLessThan(z('./alerts/AlertToast.jsx', /pointer-events-none fixed[^"]*z-\[(\d+)\]/))
  })
})
