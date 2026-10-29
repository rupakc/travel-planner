import { arrangeItinerary } from './itineraryLayout'
import { apiReturnDate } from './compare'
import { scheduleDays } from './schedule'

const RECHECK_FALLBACK = "Couldn't re-check — try again"

const withoutVerification = (section) => {
  if (!section || typeof section !== 'object') return null
  const { verification: _verification, ...rest } = section
  return rest
}

/**
 * The itinerary as the user now sees it: arranged by their layout, with
 * removed activities left out, their edits (activity/location/cost) applied
 * and estimated start/end times and travel between stops added — what
 * ItinerarySection shows.
 */
function editedItinerary(itinerary, selections) {
  const edits = selections?.itinerary_edits || {}
  const { removed: _removed, changed: _changed, verification: _verification, ...arranged } =
    arrangeItinerary(itinerary, selections?.itinerary_layout, edits)
  return {
    ...arranged,
    days: scheduleDays(arranged.days, edits).map((day) => ({
      ...day,
      slots: (day.slots || []).map((slot) => {
        const edit = edits[slot.key] || {}
        // `key` is client-only layout bookkeeping
        const { notes, key: _key, ...rest } = slot
        return {
          ...rest,
          // the original description no longer matches an edited activity
          // (same test as the on-screen row: any falsy edit keeps it)
          ...(!edit.activity && notes !== undefined ? { notes } : {}),
          activity: edit.activity ?? slot.activity,
          location: edit.location ?? slot.location,
          estimated_cost_usd: edit.cost ?? slot.estimated_cost_usd,
        }
      }),
    })),
  }
}

/** POST /api/stress-test body for re-checking the edited itinerary. */
export function buildStressTestPayload(searchData, results, selections) {
  return {
    ...searchData,
    return_date: apiReturnDate(searchData?.return_date),
    itinerary: editedItinerary(results.itinerary, selections),
    flights: withoutVerification(results.flights),
    visa: withoutVerification(results.visa),
    weather: withoutVerification(results.weather),
  }
}

/** Identifies the edited itinerary a re-check ran against (layout + edits). */
export function recheckFingerprint(itinerary, selections) {
  return JSON.stringify(editedItinerary(itinerary, selections).days)
}

/** The server's string `detail` (e.g. a 429 message), else a generic retry hint. */
export function recheckErrorMessage(err) {
  const detail = err?.response?.data?.detail
  return typeof detail === 'string' && detail.trim() ? detail : RECHECK_FALLBACK
}
