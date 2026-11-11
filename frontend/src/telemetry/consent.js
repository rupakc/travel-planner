// Telemetry consent. Devices in an EU/EEA/UK/CH timezone are opted out until
// the user chooses; everyone else is opted in and can switch it off.

import { emit } from './client'

const KEY = 'tp_consent'
const CHOICES = new Set(['granted', 'denied'])

// Europe/* zones outside the EU/EEA/UK/CH.
const EUROPE_EXCLUDED = new Set([
  'Europe/Istanbul', 'Europe/Moscow', 'Europe/Minsk', 'Europe/Kiev', 'Europe/Kyiv',
])
const ATLANTIC_INCLUDED = new Set([
  'Atlantic/Reykjavik', 'Atlantic/Canary', 'Atlantic/Madeira', 'Atlantic/Azores', 'Atlantic/Faroe',
])

function deviceTimeZone() {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || ''
  } catch {
    return ''
  }
}

export function consentRequired(tz = deviceTimeZone()) {
  if (typeof tz !== 'string' || !tz) return false
  if (tz.startsWith('Europe/')) return !EUROPE_EXCLUDED.has(tz)
  return ATLANTIC_INCLUDED.has(tz)
}

// The choice is kept in memory too, so it holds when storage throws.
let memoryChoice = null

export function getConsent() {
  try {
    const v = localStorage.getItem(KEY)
    if (CHOICES.has(v)) return v
  } catch { /* storage blocked: fall back to memory */ }
  return memoryChoice
}

export function setConsent(choice) {
  try {
    if (!CHOICES.has(choice)) return
    memoryChoice = choice
    try { localStorage.setItem(KEY, choice) } catch { /* memory only */ }
    // The client sends a grant; a denial is stored locally only: the client
    // clears its queue and sends nothing, not even the choice.
    emit('consent', { choice })
  } catch { /* never break the caller */ }
}

export function telemetryAllowed(tz) {
  try {
    const choice = getConsent()
    if (choice) return choice === 'granted'
    return !consentRequired(tz === undefined ? deviceTimeZone() : tz)
  } catch {
    return false
  }
}

export function _resetConsentForTests() {
  memoryChoice = null
}
