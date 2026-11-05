import axios from 'axios'
import { cityForCode } from '../utils/cityNames'

const api = axios.create({
  baseURL: '/api',
  headers: { 'Content-Type': 'application/json' },
})

/**
 * Stream search results using a Web Worker so SSE parsing
 * happens off the main thread, keeping the UI smooth.
 * Returns a cleanup function that terminates the worker.
 */
export function streamSearch(searchData, onResult, onDone, onError, token = null, onInterrupted = null) {
  // Vite exposes workers via `new URL(..., import.meta.url)` + `{ type: 'module' }`
  const worker = new Worker(
    new URL('../workers/sseWorker.js', import.meta.url),
    { type: 'module' }
  )

  worker.onmessage = ({ data }) => {
    if (data.type === '__error') {
      onError(new Error(data.message))
      worker.terminate()
    } else if (data.type === '__interrupted') {
      // Stream severed before the server's `done` event — let the caller
      // retry; fall back to a normal completion if it can't.
      ;(onInterrupted || onDone)()
      worker.terminate()
    } else if (data.type === '__stream_end' || data.type === 'done') {
      onDone()
      worker.terminate()
    } else {
      onResult(data.type, data.data, data.source)
    }
  }

  worker.onerror = (e) => {
    onError(new Error(e.message || 'Worker error'))
    worker.terminate()
  }

  worker.postMessage({
    url: '/api/search',
    headers: {
      'Content-Type': 'application/json',
      // Auth is optional on /api/search — when present, the backend injects
      // the user's learned Taste Graph profile into agent prompts.
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(searchData),
  })

  return () => worker.terminate()
}

export async function searchFlightsFiltered(searchData, filters) {
  const payload = {
    origin: searchData.origin,
    destination: searchData.destination,
    departure_date: searchData.departure_date,
    return_date: searchData.return_date || null,
    interests: searchData.interests || [],
    nationality: searchData.nationality || '',
    residence_permits: searchData.residence_permits || [],
    existing_visas: searchData.existing_visas || [],
    budget_usd: searchData.budget_usd || null,
    num_travelers: searchData.num_travelers || 1,
    ...filters,
  }
  const res = await api.post('/flights/filtered', payload)
  return res.data
}

export async function searchHotelsFiltered(searchData, filters) {
  const payload = {
    origin: searchData.origin,
    destination: searchData.destination,
    departure_date: searchData.departure_date,
    return_date: searchData.return_date || null,
    interests: searchData.interests || [],
    nationality: searchData.nationality || '',
    residence_permits: searchData.residence_permits || [],
    existing_visas: searchData.existing_visas || [],
    budget_usd: searchData.budget_usd || null,
    num_travelers: searchData.num_travelers || 1,
    ...filters,
  }
  const res = await api.post('/hotels/filtered', payload)
  return res.data
}

export async function searchActivitiesFiltered(searchData, filters) {
  const payload = {
    origin: searchData.origin,
    destination: searchData.destination,
    departure_date: searchData.departure_date,
    return_date: searchData.return_date || null,
    interests: searchData.interests || [],
    nationality: searchData.nationality || '',
    residence_permits: searchData.residence_permits || [],
    existing_visas: searchData.existing_visas || [],
    budget_usd: searchData.budget_usd || null,
    num_travelers: searchData.num_travelers || 1,
    ...filters,
  }
  const res = await api.post('/activities/filtered', payload)
  return res.data
}

/**
 * Cheapest live fare for departure dates ±3 days (same trip length).
 * Single-city trips only; needs a signed-in user.
 */
export async function fetchFareCalendar(searchData, token) {
  const res = await api.post('/flights/fare-calendar', searchData, token ? authHeaders(token) : undefined)
  return res.data
}

// One /health read per page load; a failed read is not cached so it can retry.
let capabilities = null

/** Server capability flags from /health: live fares, fare watch, email alerts. */
export function getCapabilities() {
  if (!capabilities) {
    capabilities = fetch('/health')
      .then(res => (res.ok ? res.json() : Promise.reject(new Error(`HTTP ${res.status}`))))
      .then(data => ({
        serpapi: data?.serpapi_configured === true,
        fareWatch: data?.fare_watch_available === true,
        email: data?.email_alerts_available === true,
      }))
      .catch(() => {
        capabilities = null
        return { serpapi: false, fareWatch: false, email: false }
      })
  }
  return capabilities
}

/** Whether the backend has live flight data (SerpAPI) configured. */
export function getSerpapiConfigured() {
  return getCapabilities().then(c => c.serpapi)
}

export async function discoverDestinations(data) {
  const res = await api.post('/discover', data)
  return res.data
}

const authHeaders = (token) => ({ headers: { Authorization: `Bearer ${token}` } })

export async function getRecentSearches(token) {
  const res = await api.get('/recent-searches', authHeaders(token))
  return res.data
}

export async function saveRecentSearch(token, search) {
  const res = await api.post('/recent-searches', search, authHeaders(token))
  return res.data
}

export async function deleteRecentSearch(token, id) {
  await api.delete(`/recent-searches/${encodeURIComponent(id)}`, authHeaders(token))
}

export default api

/** Per-destination lightweight summary for trip comparison. */
export async function compareDestination(request, token) {
  const res = await api.post('/compare/destination', request, authHeaders(token))
  return res.data
}

// Re-run the Trip Health Check against the user's edited itinerary.
// Auth is optional on /api/stress-test.
export async function recheckStressTest(payload, token) {
  const res = await api.post('/stress-test', payload, token ? authHeaders(token) : undefined)
  return res.data
}

// Plan from a link: read a link, pasted text or screenshots and return the
// places found (an ImportPreview). `signal` lets the traveller cancel.
export async function extractImport(body, token, signal) {
  const res = await api.post('/import/extract', body, { ...authHeaders(token), signal, timeout: 90000 })
  return res.data
}

// Place one "Couldn't place" spot in the town the traveller typed.
export async function resolveImportPlace(body, token) {
  const res = await api.post('/import/resolve-place', body, authHeaders(token))
  return res.data
}

// ── Fare watches + notifications ─────────────────────────────────────────────

export async function listFareWatches(token) {
  return (await api.get('/fare-watches', authHeaders(token))).data
}

/** The signed-in user's watch for this trip, or null (no live lookups). */
export async function matchFareWatch(trip, token) {
  return (await api.post('/fare-watches/match', trip, authHeaders(token))).data.watch
}

export async function createFareWatch(body, token) {
  return (await api.post('/fare-watches', body, authHeaders(token))).data
}

export async function updateFareWatch(id, changes, token) {
  return (await api.patch(`/fare-watches/${id}`, changes, authHeaders(token))).data
}

export async function deleteFareWatch(id, token) {
  await api.delete(`/fare-watches/${id}`, authHeaders(token))
}

export async function checkFareWatchNow(id, token) {
  return (await api.post(`/fare-watches/${id}/check`, null, authHeaders(token))).data
}

// ── Price watches (hotel / activity / trip) ──────────────────────────────────
// Bodies nest the kind's spec under its kind: { kind: 'hotel', hotel: {...} }
// (see utils/priceWatch.priceWatchBody). A 422 with data.code ===
// 'no_live_price' carries data.message, data.suggestions and data.estimate.

export async function listPriceWatches(token, kind = null) {
  const params = kind ? { kind } : undefined
  return (await api.get('/price-watches', { ...authHeaders(token), params })).data
}

/** The city an airport code names ("LIS" → "Lisbon"), from the local airport data, or null. */
export async function airportCity(code) {
  const rows = (await api.get('/airports/search', { params: { q: code, limit: 5 } })).data
  return cityForCode(code, rows)
}

/** The signed-in user's watch for this subject, or null (no live lookups). */
export async function matchPriceWatch(body, token) {
  return (await api.post('/price-watches/match', body, authHeaders(token))).data.watch
}

export async function createPriceWatch(body, token) {
  return (await api.post('/price-watches', body, authHeaders(token))).data
}

export async function updatePriceWatch(id, changes, token) {
  return (await api.patch(`/price-watches/${id}`, changes, authHeaders(token))).data
}

export async function deletePriceWatch(id, token) {
  await api.delete(`/price-watches/${id}`, authHeaders(token))
}

export async function checkPriceWatchNow(id, token) {
  return (await api.post(`/price-watches/${id}/check`, null, authHeaders(token))).data
}

export async function getUnreadCount(token) {
  return (await api.get('/notifications/unread-count', authHeaders(token))).data.count
}

export async function listNotifications(token, { unreadOnly = false, limit = 10, offset = 0 } = {}) {
  const params = { unread_only: unreadOnly, limit, offset }
  return (await api.get('/notifications', { ...authHeaders(token), params })).data
}

/** Mark notifications read: `ids`, or every one when ids is 'all'. */
export async function markNotificationsRead(ids, token) {
  const body = ids === 'all' ? { all: true } : { ids }
  return (await api.post('/notifications/read', body, authHeaders(token))).data
}

export async function updateAccountEmail(email, token) {
  return (await api.put('/auth/email', { email }, authHeaders(token))).data
}
