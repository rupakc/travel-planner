// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'

vi.mock('../telemetry/client', () => ({ emit: vi.fn() }))

import i18n from 'i18next'
import '../i18n'
import { _resetConsentForTests, getConsent, telemetryAllowed } from '../telemetry/consent'
import ConsentPrompt, { PrivacySwitch } from './ConsentPrompt'

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
