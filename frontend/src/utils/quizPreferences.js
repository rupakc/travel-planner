// Quiz answers → server Preferences, ported from Android
// core/domain/.../profile/PreferencesMapping.kt (`Preferences.mergeQuizAnswers`).
// `PUT /api/preferences` replaces every field, so callers read first, merge
// here, and send the whole object back. The merge never wipes anything:
// - interests / accessibility_needs: union, existing first, web ids only;
// - budget_category: set when the budget question was answered;
// - adults / children: from the companions answer only while the server still
//   holds the default party (1 adult, nobody else); seniors never change;
// - infants: at least 1 for "travelling with infants" (a minimum, on any party);
// - num_travelers = adults + children + seniors + infants, clamped 1..20, only
//   when a count changed;
// - every other field is kept as is.
import { chosenAll, chosenFor } from './travellerQuiz'

const MAX_TRAVELLERS = 20

// The server's DEFAULT_PREFS (backend/app/db/preferences_db.py), used for
// fields an older row may lack.
const DEFAULTS = {
  budget_category: 'medium',
  nationality: '',
  current_residence: '',
  residence_permits: [],
  existing_visas: [],
  interests: [],
  num_travelers: 1,
  adults: 1,
  children: 0,
  seniors: 0,
  infants: 0,
  accessibility_needs: [],
}

const int = (v, fallback) => (Number.isInteger(v) ? v : fallback)
const list = (v) => (Array.isArray(v) ? v : [])
const clamp = (n, lo, hi) => Math.min(hi, Math.max(lo, n))

export function mergeQuizAnswers(prefs, answers) {
  const base = { ...DEFAULTS, ...(prefs && typeof prefs === 'object' ? prefs : {}) }
  const adults = int(base.adults, 1)
  const children = int(base.children, 0)
  const seniors = int(base.seniors, 0)
  const infants = int(base.infants, 0)

  const chosen = chosenAll(answers)
  const interests = [...new Set([...list(base.interests), ...chosen.flatMap((o) => o.interestIds || [])])]
  const needs = [...new Set([...list(base.accessibility_needs), ...chosen.map((o) => o.accessibilityId).filter(Boolean)])]
  const budget = chosenFor(answers, 'budget')[0]?.budgetCategory ?? base.budget_category

  const defaultParty = adults === 1 && children === 0 && seniors === 0 && infants === 0
  const counts = defaultParty ? chosenFor(answers, 'companions')[0]?.travellers : null
  const adultsOut = counts ? counts.adults : adults
  const childrenOut = counts ? counts.children : children
  const infantsOut = chosen.some((o) => o.addsInfant) ? Math.max(infants, 1) : infants
  const changed = adultsOut !== adults || childrenOut !== children || infantsOut !== infants

  return {
    ...base,
    interests,
    accessibility_needs: needs,
    budget_category: budget,
    adults: adultsOut,
    children: childrenOut,
    seniors,
    infants: infantsOut,
    num_travelers: changed
      ? clamp(adultsOut + childrenOut + seniors + infantsOut, 1, MAX_TRAVELLERS)
      : int(base.num_travelers, 1),
  }
}

/** The pace answer (`relaxed` / `balanced` / `packed`) for the search form, or null. */
export const quizPace = (answers) => chosenFor(answers, 'pace')[0]?.pace ?? null

// ── device storage: answers in localStorage tp_quiz_<user_id> ───────────────
const quizKey = (userId) => `tp_quiz_${userId}`
const airportKey = (userId) => `tp_home_airport_${userId}`

function read(key) {
  try { return window.localStorage.getItem(key) } catch { return null }
}
function write(key, value) {
  try {
    if (value === null || value === '') window.localStorage.removeItem(key)
    else window.localStorage.setItem(key, value)
  } catch { /* storage blocked */ }
}

/** The saved answers for this user, `{}` when none (or unreadable). */
export function loadQuizAnswers(userId) {
  if (!userId) return {}
  try {
    const parsed = JSON.parse(read(quizKey(userId)))
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {}
  } catch {
    return {}
  }
}

export function saveQuizAnswers(userId, answers) {
  if (userId) write(quizKey(userId), JSON.stringify(answers || {}))
}

/** The home airport (IATA code or typed text) picked in onboarding; device-only. */
export const loadHomeAirport = (userId) => (userId ? read(airportKey(userId)) || '' : '')
export function saveHomeAirport(userId, value) {
  if (userId) write(airportKey(userId), value || '')
}
