// @vitest-environment jsdom
import { describe, it, expect, afterEach, vi } from 'vitest'

const emit = vi.fn()
vi.mock('./client', () => ({ emit: (...a) => emit(...a) }))

import { consentRequired, getConsent, setConsent, telemetryAllowed, _resetConsentForTests } from './consent'

afterEach(() => {
  vi.restoreAllMocks()
  emit.mockClear()
  try { localStorage.clear() } catch { /* ignore */ }
  _resetConsentForTests()
})

describe('consentRequired', () => {
  it('is true for EU/EEA/UK/CH timezones', () => {
    expect(consentRequired('Europe/Berlin')).toBe(true)
    expect(consentRequired('Europe/London')).toBe(true)
    expect(consentRequired('Europe/Zurich')).toBe(true)
    expect(consentRequired('Atlantic/Reykjavik')).toBe(true)
    expect(consentRequired('Atlantic/Canary')).toBe(true)
    expect(consentRequired('Atlantic/Madeira')).toBe(true)
    expect(consentRequired('Atlantic/Azores')).toBe(true)
    expect(consentRequired('Atlantic/Faroe')).toBe(true)
  })

  it('is false elsewhere, including non-EEA Europe/* zones', () => {
    expect(consentRequired('Asia/Kolkata')).toBe(false)
    expect(consentRequired('America/New_York')).toBe(false)
    expect(consentRequired('Europe/Istanbul')).toBe(false)
    expect(consentRequired('Europe/Moscow')).toBe(false)
    expect(consentRequired('Europe/Minsk')).toBe(false)
    expect(consentRequired('Europe/Kiev')).toBe(false)
    expect(consentRequired('Europe/Kyiv')).toBe(false)
    expect(consentRequired('Atlantic/Bermuda')).toBe(false)
  })

  it('treats a missing or odd timezone as not required', () => {
    expect(consentRequired('')).toBe(false)
    expect(consentRequired(undefined)).toBe(consentRequired())
    expect(consentRequired(42)).toBe(false)
  })
})

describe('getConsent / setConsent / telemetryAllowed', () => {
  it('starts with no choice', () => {
    expect(getConsent()).toBe(null)
  })

  it('stores the choice and tells the client (which sends nothing for a denial)', () => {
    setConsent('granted')
    expect(getConsent()).toBe('granted')
    expect(emit).toHaveBeenCalledWith('consent', { choice: 'granted' })
    setConsent('denied')
    expect(getConsent()).toBe('denied')
    // the client turns this into "clear the queue, send nothing" (client.test.js)
    expect(emit).toHaveBeenLastCalledWith('consent', { choice: 'denied' })
  })

  it('ignores invalid choices', () => {
    setConsent('maybe')
    expect(getConsent()).toBe(null)
    expect(emit).not.toHaveBeenCalled()
  })

  it('allows telemetry when granted, or when no choice and not required', () => {
    expect(telemetryAllowed('Asia/Kolkata')).toBe(true)
    expect(telemetryAllowed('Europe/Berlin')).toBe(false)
    setConsent('granted')
    expect(telemetryAllowed('Europe/Berlin')).toBe(true)
    setConsent('denied')
    expect(telemetryAllowed('Asia/Kolkata')).toBe(false)
  })

  it('survives storage that throws (keeps the choice in memory)', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('denied') })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('denied') })
    expect(getConsent()).toBe(null)
    expect(() => setConsent('denied')).not.toThrow()
    expect(getConsent()).toBe('denied')
    expect(telemetryAllowed('Asia/Kolkata')).toBe(false)
  })
})
