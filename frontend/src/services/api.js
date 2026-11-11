import axios from 'axios'
import { watchAxios, isSessionRevoked, reportSessionRevoked } from './sessionRevoked'
import { errorCodeText } from '../utils/httpError'
import { cityForCode } from '../utils/cityNames'
import i18n from '../i18n'
import { isSupportedLanguage } from '../i18n/languages'

const api = watchAxios(axios.create({
  baseURL: '/api',
  headers: { 'Content-Type': 'application/json' },
}))

/**
 * `{ locale }` for AI-calling requests: the UI language's base code (zh-CN ->
 * zh), only when it is one the backend accepts, so an unsupported language
 * gets no field at all and the AI answers in English.
 */
export function localeField() {
  const base = String(i18n.language || '').split('-')[0].toLowerCase()
  return isSupportedLanguage(base) ? { locale: base } : {}
}

/**
 * The Error for an SSE worker's `__error` message ({message, code, status}):
 * the translated `error_code` when there is one (email_unverified,
 * ai_daily_quota, …), else the server's detail. A 401 session_revoked is
 * reported with the token the stream was opened with.
 */
export function workerError(data, token = null) {
  if (isSessionRevoked(data?.status, { error_code: data?.code })) reportSessionRevoked(token)
  return new Error(errorCodeText(data?.code) || data?.message || 'Request failed')
}

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
      onError(workerError(data, token))
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
    body: JSON.stringify({ ...searchData, ...localeField() }),
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
    ...localeField(),
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
    ...localeField(),
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
    ...localeField(),
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
  const res = await api.post('/discover', { ...data, ...localeField() })
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

// Create (or reuse) a plan's public share link -> {share_token}
export async function sharePlan(token, planId) {
  const res = await api.post(`/plans/${planId}/share`, null, authHeaders(token))
  return res.data
}

export default api

/** Per-destination lightweight summary for trip comparison. */
export async function compareDestination(request, token) {
  const res = await api.post('/compare/destination', { ...request, ...localeField() }, authHeaders(token))
  return res.data
}

// Re-run the Trip Health Check against the user's edited itinerary.
// Auth is optional on /api/stress-test.
export async function recheckStressTest(payload, token) {
  const res = await api.post('/stress-test', { ...payload, ...localeField() }, token ? authHeaders(token) : undefined)
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

/** Admin analytics: daily users/sessions/events, top events and screens (days 1-90). */
export async function getTelemetrySummary(days = 30, token) {
  return (await api.get('/admin/telemetry/summary', { ...authHeaders(token), params: { days } })).data
}

// ── Near me (v2) and "Search the web now" ───────────────────────────────────
// Both answers are live, grounded results for the signed-in user only: callers
// keep them in component state and never write them to storage or caches.

/** Places to see / eat / shop / stay around a point (Google Maps grounding). */
export async function fetchNearby({ lat, lng, language = 'en' }, token) {
  return (await api.post('/nearby', { lat, lng, sections: true, language }, authHeaders(token))).data
}

/** One live web search for a watch the user owns (kind: flight | hotel | activity | trip). */
export async function liveCheckWatch(kind, watchId, token) {
  return (await api.post('/live-check', { kind, watch_id: watchId }, authHeaders(token))).data
}

// Sign-in providers the backend has configured. Any failure (404 on an older
// backend, network, 5xx) means "none configured": never throws to the UI.
export async function getAuthProviders() {
  try {
    const list = (await api.get('/auth/providers')).data?.providers
    return Array.isArray(list) ? list : []
  } catch {
    return []
  }
}
