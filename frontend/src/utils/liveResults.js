/**
 * Pure helpers for the two live, grounded features — Near me (Google Maps
 * grounding) and "Search the web now" on watched prices (Google Search
 * grounding). Results are shown once to the user who asked and kept only in
 * component state: nothing here reads or writes storage.
 */
import i18n from '../i18n'

const tt = (key, opts) => i18n.t(`misc:${key}`, opts)

/** The four Near me sections, in display order (titles used when the API omits one). */
export const NEARBY_SECTIONS = ['see', 'eat', 'shop', 'stay'].map((id) => ({
  id,
  get title() { return tt(`nearby.section.${id}`) },
}))

/** The four sections in order, each with an `items` array (missing ones are empty). */
export function nearbySections(data) {
  const byId = new Map((Array.isArray(data?.sections) ? data.sections : []).map(s => [s?.id, s]))
  return NEARBY_SECTIONS.map(({ id, title }) => {
    const s = byId.get(id)
    return {
      id,
      title: (typeof s?.title === 'string' && s.title) || title,
      items: Array.isArray(s?.items) ? s.items.filter(i => i && i.name) : [],
      empty: tt(`nearby.empty.${id}`),
    }
  })
}

/** An http(s) URL as a string, or null — grounded links are never rendered as other schemes. */
export function safeHttpUrl(uri) {
  if (typeof uri !== 'string' || !uri) return null
  try {
    const u = new URL(uri)
    return u.protocol === 'https:' || u.protocol === 'http:' ? u.href : null
  } catch {
    return null
  }
}

/** Sources with a usable link, keeping their original index (quotes cite by index). */
export function usableSources(sources) {
  return (Array.isArray(sources) ? sources : [])
    .map((s, index) => ({ index, title: s?.title || s?.uri || tt('live.source'), uri: safeHttpUrl(s?.uri) }))
    .filter(s => s.uri)
}

/** Google Search link for one "Searched for" query. */
export function googleSearchUrl(query) {
  return `https://www.google.com/search?q=${encodeURIComponent(query)}`
}

const fold = (v) => String(v).normalize('NFD').replace(/[\u0300-\u036f]/g, '').trim().toLowerCase()

/** "Lisbon, Portugal" — the region and country are left out when they repeat a part before them. */
export function placeLabel(place) {
  if (!place) return ''
  const parts = []
  for (const part of [place.name, place.region, place.country]) {
    if (typeof part !== 'string' || !part.trim()) continue
    if (parts.some(p => fold(p) === fold(part))) continue
    parts.push(part.trim())
  }
  return parts.join(', ')
}

/** The browser's language tag for the API (BCP-47, 2–35 chars), else 'en'. */
export function browserLanguage(nav = typeof navigator !== 'undefined' ? navigator : null) {
  const tag = nav?.language
  return typeof tag === 'string' && /^[A-Za-z0-9_-]{2,35}$/.test(tag) ? tag : 'en'
}

/** Coordinates as sent to the API: ~100 m precision is plenty for "near me". */
export function roundCoord(v) {
  return Math.round(v * 1000) / 1000
}

/**
 * What to tell the user when a live request fails. Handles the string
 * `detail` (429 rate limit, 404 "Watch not found") and the `{code, message}`
 * details (404 no_place, 409 watch_expired, 502 agent_error / live_check_failed, 503 ai_limit /
 * ai_billing / grounding_unavailable).
 * @param {unknown} err  axios error
 * @param {'nearby'|'live'} scope
 * @returns {{ code: string, text: string, retry: boolean }}
 */
export function liveErrorMessage(err, scope = 'live') {
  const res = err && typeof err === 'object' ? err.response : null
  const status = typeof res?.status === 'number' ? res.status : null
  const detail = res?.data?.detail
  const str = typeof detail === 'string' && detail.trim() ? detail.trim() : null
  const code = detail && typeof detail === 'object' && typeof detail.code === 'string' ? detail.code : null
  const message = detail && typeof detail === 'object' && typeof detail.message === 'string' && detail.message.trim()
    ? detail.message.trim() : null
  const near = scope === 'nearby'

  if (status === null) {
    return { code: 'network', retry: true, text: tt('nearby.api.network') }
  }
  if (status === 429) {
    return { code: 'rate_limited', retry: true, text: str || tt('live.rateLimited') }
  }
  if (status === 503 && (code === 'ai_limit' || code === 'ai_billing')) {
    return { code, retry: false, text: message || tt(`live.${code === 'ai_limit' ? 'aiLimit' : 'aiBilling'}`) }
  }
  if (status === 503 && code === 'grounding_unavailable') {
    return {
      code, retry: false,
      text: near ? tt('nearby.api.grounding_unavailable') : tt('live.groundingWeb'),
    }
  }
  if (status === 404) {
    if (near) {
      return { code: 'no_place', retry: false, text: message || tt('live.noPlace') }
    }
    return { code: 'not_found', retry: false, text: tt('live.notFound') }
  }
  if (status === 409 && code === 'watch_expired') {
    return { code, retry: false, text: tt('live.watchExpired') }
  }
  if (status === 401) {
    return { code: 'signed_out', retry: false, text: tt('live.signedOut') }
  }
  if (status === 502) {
    return {
      code: code || 'failed', retry: true,
      text: message || (near ? tt('live.agentNear') : tt('live.agentWeb')),
    }
  }
  return {
    code: 'failed', retry: true,
    text: str || (near ? tt('live.failedNear') : tt('live.failedWeb')),
  }
}

/** Plain words for a browser geolocation failure (GeolocationPositionError codes, or 'unsupported'). */
export function geoErrorMessage(code) {
  switch (code) {
    case 1:
      return {
        code: 'denied',
        text: tt('nearby.geo.denied'),
      }
    case 2:
      return { code: 'unavailable', text: tt('nearby.geo.unavailable') }
    case 3:
      return { code: 'timeout', text: tt('nearby.geo.timeout') }
    default:
      return { code: 'unsupported', text: tt('nearby.geo.unsupported') }
  }
}
