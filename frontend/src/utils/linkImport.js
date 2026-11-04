// Plan a trip from a link, pasted text or screenshots — pure helpers for the
// Search page's "From a link" mode and the Results page's link banner.

export const MAX_MUST_INCLUDE = 25
export const MAX_IMAGES = 4
export const MAX_IMAGE_BYTES = 5 * 1024 * 1024
const IMAGE_TYPES = new Set(['image/png', 'image/jpeg', 'image/webp', 'image/gif'])

export const IMPORT_EXAMPLES = [
  {
    label: '48 hours in Lisbon',
    text: '48 hours in Lisbon: lunch at Time Out Market, Belém Tower and custard tarts at Pastéis de Belém, browse LX Factory, sunset at Miradouro da Senhora do Monte, then a day trip to Pena Palace in Sintra.',
  },
  {
    label: "A friend's Tokyo tips",
    text: 'Tokyo musts from my trip!! Tsukiji Outer Market for breakfast, teamLab Planets (book ahead), Senso-ji at dawn before the crowds, drinks in Golden Gai, and Shibuya Sky at sunset. If you have time, Hakone for the onsen.',
  },
  {
    label: 'Rome and Florence',
    text: 'Day 1–2 Rome: Colosseum, dinner in Trastevere, the Pantheon, gelato at Giolitti. Day 3–4 Florence: the Uffizi, climb the Duomo, Piazzale Michelangelo at sunset and lunch at Mercato Centrale.',
  },
]

const URL_LIKE = /^(https?:\/\/)?([a-z0-9-]+\.)+[a-z]{2,}(:\d+)?([/?#]\S*)?$/i

/** What the traveller typed: a link, some text, or nothing. */
export function detectImportInput(raw) {
  const text = (raw || '').trim()
  if (!text) return { kind: 'empty' }
  if (!/\s/.test(text) && URL_LIKE.test(text)) {
    return { kind: 'url', url: /^https?:\/\//i.test(text) ? text : `https://${text}` }
  }
  return { kind: 'text' }
}

const FRIENDLY = {
  network: "We couldn't reach Voyager. Check your connection and try again.",
  unknown: 'Something went wrong while reading that. Try again in a moment.',
}
// What the error card offers: switch to pasted text / screenshots, or retry
const ACTIONS = {
  blocked_source: ['text', 'images'],
  paywall: ['text', 'images'],
  empty_page: ['text', 'images'],
  unsupported_content: ['images'],
  not_found: ['text'],
  no_places: ['text'],
  timeout: ['retry', 'text'],
  unreachable: ['retry', 'text'],
  http_error: ['retry', 'text'],
  extract_failed: ['retry'],
  network: ['retry'],
  unknown: ['retry'],
}

/** {code, message, actions} for a failed import call, or null when cancelled. */
export function importErrorView(err) {
  if (err?.code === 'ERR_CANCELED' || err?.name === 'CanceledError' || err?.name === 'AbortError') return null
  const res = err?.response
  if (!res) return { code: 'network', message: FRIENDLY.network, actions: ACTIONS.network }
  const detail = res.data?.detail
  if (detail && typeof detail === 'object' && detail.code) {
    return { code: detail.code, message: detail.message || FRIENDLY.unknown, actions: ACTIONS[detail.code] || [] }
  }
  if (res.status === 429 && typeof detail === 'string') {
    return { code: 'rate_limited', message: detail, actions: [] }
  }
  return { code: 'unknown', message: FRIENDLY.unknown, actions: ACTIONS.unknown }
}

/** Why a dropped file can't be used, or null when it's fine. */
export function checkImageFile(file) {
  const type = (file?.type || '').toLowerCase()
  const name = (file?.name || '').toLowerCase()
  if (type === 'image/heic' || type === 'image/heif' || /\.hei[cf]$/.test(name)) {
    return 'iPhone HEIC photos can\'t be read yet — take a screenshot instead (screenshots are PNG), or export it as JPEG.'
  }
  if (!IMAGE_TYPES.has(type)) return `${file?.name || 'That file'} isn't an image we can read. Use PNG, JPEG, WebP or GIF.`
  if (file.size > MAX_IMAGE_BYTES) return `${file.name || 'That image'} is over 5 MB. Crop it or save it as a smaller PNG or JPEG.`
  return null
}

const addDaysIso = (iso, days) => {
  const [y, m, d] = iso.split('-').map(Number)
  return new Date(Date.UTC(y, m - 1, d + days)).toISOString().slice(0, 10)
}

/** A month out by default, lasting `nights`. */
export function defaultImportDates(today, nights) {
  const departure = addDaysIso(today, 30)
  return { departure_date: departure, return_date: addDaysIso(departure, Math.max(1, nights || 1)) }
}

/** Editable review state for a preview. */
// Hotels a post mentions are worth seeing, not scheduling: they start unticked
export function previewToDraft(preview) {
  let ticked = 0
  return {
    places: (preview.places || []).map((p) => {
      const selected = p.kind !== 'stay' && ticked < MAX_MUST_INCLUDE
      if (selected) ticked += 1
      return { ...p, selected }
    }),
    unresolved: (preview.unresolved || []).map((p) => ({ ...p, destination: null, selected: true })),
    stops: (preview.destinations || []).map((d) => ({ ...d, included: true })),
  }
}

/**
 * The Search form and on-the-way stops for planning the reviewed import
 * (fed to SearchPage's normal startSearch). Places of excluded stops are
 * dropped; at most MAX_MUST_INCLUDE places go in, in order.
 */
export function buildImportSearch({ form, preview, draft }) {
  const stops = draft.stops.filter((s) => s.included)
  const byName = new Map(stops.map((s) => [s.name, s]))
  const chosen = [...draft.places, ...draft.unresolved]
    .filter((p) => p.selected && p.destination && byName.has(p.destination))
    .slice(0, MAX_MUST_INCLUDE)
  const must_include = chosen.map((p) => {
    const stop = byName.get(p.destination)
    const exact = !p.approximate && p.lat != null && p.lng != null
    return {
      name: p.name.trim(),
      kind: p.kind || 'sight',
      city: stop.city,
      town: p.city && p.city !== stop.city ? p.city : null,
      lat: exact ? p.lat : null,
      lng: exact ? p.lng : null,
      note: p.note || null,
      quote: p.quote || null,
      verified: !!p.verified,
    }
  })
  const nights = stops.reduce((n, s) => n + Math.max(1, s.nights || 1), 0)
  const last = stops.at(-1)
  const interests = [...new Set([...(form.interests || []), ...(preview.interests || [])])]
  const source = preview.source || {}
  return {
    form: {
      ...form,
      destination: last?.name || '',
      return_date: addDaysIso(form.departure_date, Math.max(1, nights)),
      interests,
      must_include,
      import_source: { url: source.kind === 'url' ? source.url || null : null, title: preview.title || source.title || null },
    },
    stops: stops.slice(0, -1).map((s) => ({ city: s.name, nights: s.nights })),
  }
}

/** The Results banner's numbers, or null for a trip without a link. */
export function linkCoverageSummary(searchData, itinerary) {
  const wanted = searchData?.must_include || []
  if (!wanted.length) return null
  const title = searchData.import_source?.title || null
  if (!itinerary?.days?.length && !itinerary?.link_coverage) return { total: wanted.length, inItinerary: 0, missing: [], title, pending: true }
  const cov = itinerary.link_coverage
  if (cov) {
    const inItinerary = (cov.scheduled?.length || 0) + (cov.extras?.length || 0)
    return { total: wanted.length, inItinerary, missing: cov.missing || [], title, pending: false }
  }
  const linked = new Set()
  for (const day of itinerary.days || []) {
    for (const slot of day.slots || []) {
      if (!slot.from_link) continue
      for (const name of slot.link_places?.length ? slot.link_places : [slot.link_place]) if (name) linked.add(name)
    }
    for (const x of day.link_extras || []) linked.add(x.name)
  }
  const missing = wanted.map((p) => p.name).filter((n) => !linked.has(n))
  return { total: wanted.length, inItinerary: wanted.length - missing.length, missing, title, pending: false }
}

/** The Search page link that opens the import flow prefilled with `url`. */
export function chatImportLink(url) {
  return `/?import=${encodeURIComponent(url)}`
}

/** The http(s) link in a `?import=` query string, or null. */
export function importLinkFromQuery(search) {
  const value = new URLSearchParams(search || '').get('import')
  if (!value) return null
  try {
    const url = new URL(value.trim())
    return url.protocol === 'https:' || url.protocol === 'http:' ? value.trim() : null
  } catch {
    return null
  }
}

/** A dropped or pasted image file → the API's {media_type, data_base64}. */
export function readImageFile(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      const result = String(reader.result || '')
      const comma = result.indexOf(',')
      resolve({ media_type: file.type, data_base64: result.slice(comma + 1) })
    }
    reader.onerror = () => reject(reader.error)
    reader.readAsDataURL(file)
  })
}
