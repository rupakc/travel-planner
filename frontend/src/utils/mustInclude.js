// Client mirror of backend/app/services/must_include.py. It is used on the
// itinerary the browser builds itself when the stream ends without one, so
// imported places are placed the same way the server places them.
// Keep the two sides in step: utils/mustInclude.test.js mirrors the backend
// tests.

const DURATION = { food: 1.5, drink: 1.5, nightlife: 2.5, shopping: 2, nature: 3, activity: 3, event: 3, area: 2.5, stay: 1, transport: 1 }
const MEAL_KINDS = new Set(['food', 'drink', 'nightlife'])
const FREE_TIME = /\bfree (time|morning|afternoon|evening)\b|at your own pace|\bleisure\b|\brelax|\brest\b|\boptional\b|explore the neighbou?rhood|spontaneous/i
const LOGISTICS = /\b(arriv\w*|depart\w*|check(?:ing)?[- ]?(?:in|into|out)|flights?|fly|flying|airports?|transfers?|trains?|rail\w*|shinkansen|tgv|eurostar|intercity|bus(?:es)?|coach|ferr(?:y|ies)|drive|driving|car hire|rental car|taxi|uber|travel (?:from|to)|head(?:ing)? (?:to|back)|move on|pack\w*|luggage|comboio|zug|tren|treno|autobus)\b|→|->/i
const LOGISTICS_TYPES = new Set(['transport', 'transit', 'travel', 'transfer', 'arrival', 'departure', 'check-in', 'check-out', 'checkin', 'checkout', 'logistics'])
const NAME_FILLER = new Set('the a an of and at in on de da do das dos di del della la le les el los las y e et und'.split(' '))
const STALE_FIELDS = ['estimated_cost_usd', 'cost', 'price_usd', 'booking_url', 'url', 'link', 'tickets', 'transport', 'transport_mode', 'notes', 'start_time', 'end_time', 'category', 'type']
const LINK_FIELDS = ['from_link', 'link_place', 'link_places', 'link_quote', 'link_note']

export const foldText = (text) => String(text || '')
  .toLowerCase()
  .replace(/ß/g, 'ss')
  .normalize('NFKD')
  .replace(/[̀-ͯ]/g, '')
// Hyphens, spaces and apostrophes all split words; a possessive 's is dropped
const tokens = (text) => foldText(String(text || '').replace(/(\w)['’]s\b/g, '$1'))
  .split(/[^a-z0-9]+/)
  .filter((t) => t && !NAME_FILLER.has(t))
const cityKey = (text) => foldText(String(text || '').split(',')[0]).trim()

/**
 * `text` names the place: the name's tokens as one contiguous, ordered phrase.
 * Spacing variants count only when they line up on whole tokens
 * ("Senso-ji" ~ "Sensoji", "Time Out" ~ "TimeOut"), so "Tokyo Tower" is not
 * "Tokyo Skytree … tallest tower" and "Ark Hills" is not "Park Hills".
 */
export function sameLinkPlace(name, text) {
  const wanted = tokens(name).join('')
  if (!wanted) return false
  const have = tokens(text)
  for (let i = 0; i < have.length; i++) {
    let joined = ''
    for (let j = i; j < have.length; j++) {
      joined += have[j]
      if (joined === wanted) return true
      if (!wanted.startsWith(joined)) break
    }
  }
  return false
}

// Arrival, departure and hotel logistics never stand for a place
const ARRIVAL = /\b(arriv\w*|depart\w*|check(?:ing)?[- ]?(?:in|into|out)|flights?|fly|flying|airports?|pack\w*|luggage)\b|\btransfer\b.*\bhotel\b/i
const ARRIVAL_TYPES = new Set(['arrival', 'departure', 'check-in', 'check-out', 'checkin', 'checkout'])
const TRANSIT_SEPARATOR = /[–—⇒→]|->|\s-\s|\bto\b|\bvia\b/i
const escapeRe = (t) => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

const isArrivalSlot = (slot) => ARRIVAL_TYPES.has(String(slot?.category || slot?.type || '').trim().toLowerCase())
  || ARRIVAL.test(String(slot?.activity || ''))

/** "Lisbon – Porto on the Alfa Pendular": two of the trip's stops with a separator between. */
function namesTwoStops(text, stopCities) {
  const raw = String(text || '')
  const folded = foldText(raw)
  const spots = stopCities
    .map((c) => cityKey(c))
    .filter(Boolean)
    .map((key) => {
      const m = new RegExp(`(^|[^a-z0-9])(${key.split(/\s+/).map(escapeRe).join('\\s+')})(?![a-z0-9])`).exec(folded)
      return m ? { start: m.index + m[1].length, end: m.index + m[1].length + m[2].length } : null
    })
    .filter(Boolean)
    .sort((a, b) => a.start - b.start)
  for (let i = 0; i + 1 < spots.length; i++) {
    // NFKD keeps symbols such as ⇒ and – in place, so positions line up
    if (TRANSIT_SEPARATOR.test(folded.slice(spots[i].end, spots[i + 1].start))) return true
  }
  return false
}

/** Travel and hotel logistics, which are never replaced or matched. */
export function isLogisticsSlot(slot, stopCities = []) {
  const kind = String(slot?.category || slot?.type || '').trim().toLowerCase()
  if (LOGISTICS_TYPES.has(kind)) return true
  const text = String(slot?.activity || '')
  if (LOGISTICS.test(text)) return true
  const folded = foldText(text)
  if (stopCities.some((c) => {
    const key = cityKey(c)
    return key && new RegExp(`\\bto ${escapeRe(key)}\\b`).test(folded)
  })) return true
  return namesTwoStops(text, stopCities)
}

// Days per stop, mirroring TravelSearchRequest._allocate_days on the server
function allocateDays(n, totalDays, nights) {
  const requested = Array.from({ length: n }, (_, i) => (Number.isInteger(nights?.[i]) && nights[i] > 0 ? nights[i] : null))
  const fixed = requested.reduce((t, d) => t + (d || 0), 0)
  const free = requested.filter((d) => d == null).length
  const remaining = totalDays - fixed
  if (requested.some(Boolean) && remaining >= free && (free || remaining === 0)) {
    if (!free) return requested
    const bounds = Array.from({ length: free + 1 }, (_, i) => Math.round((i * remaining) / free))
    let k = 0
    return requested.map((d) => (d != null ? d : bounds[k + 1] - bounds[k++]))
  }
  const bounds = Array.from({ length: n + 1 }, (_, i) => Math.round((i * totalDays) / n))
  return Array.from({ length: n }, (_, i) => bounds[i + 1] - bounds[i])
}

/** The stop (short city name) that day `dayNumber` is in, or null for a single-city trip. */
export function cityForDay(dayNumber, searchData) {
  const stops = searchData?.destinations || []
  if (stops.length < 2) return null
  const dep = Date.parse(searchData.departure_date)
  const ret = Date.parse(searchData.return_date)
  const total = Math.max(stops.length, Number.isFinite(dep) && Number.isFinite(ret) ? Math.round((ret - dep) / 86400000) : 2 * stops.length)
  const alloc = allocateDays(stops.length, total, searchData.destination_nights)
  let cursor = 0
  for (let i = 0; i < stops.length; i++) {
    if (dayNumber - 1 < cursor + alloc[i]) return String(stops[i]).split(',')[0].trim()
    cursor += alloc[i]
  }
  return String(stops.at(-1)).split(',')[0].trim()
}

/** Every `searchData.must_include` place scheduled (or noted) in `itinerary`. */
export function ensureMustInclude(itinerary, searchData) {
  const places = searchData?.must_include || []
  if (!places.length || !itinerary?.days?.length) return itinerary
  const out = structuredClone(itinerary)
  const days = out.days.filter((d) => d && typeof d === 'object')
  const last = days.length - 1
  const stops = searchData.destinations?.length ? searchData.destinations : [searchData.destination].filter(Boolean)
  const multi = stops.length > 1
  const slotsOf = (day) => (day.slots || []).filter((s) => s && typeof s === 'object')
  const logistics = (slot) => isLogisticsSlot(slot, stops)
  const dayCity = (day) => day.city || cityForDay(day.day_number, searchData)
  const rightCity = (day, place) => !(multi && place.city && dayCity(day)) || cityKey(dayCity(day)) === cityKey(place.city)
  const travelIn = new Set(days.filter((d, i) => i > 0 && dayCity(d) && cityKey(dayCity(d)) !== cityKey(dayCity(days[i - 1]))))

  for (const day of days) for (const slot of slotsOf(day)) for (const key of LINK_FIELDS) delete slot[key]
  for (const day of days) delete day.link_extras

  const linkedPerDay = new Map()
  const bump = (day) => linkedPerDay.set(day, (linkedPerDay.get(day) || 0) + 1)
  const mark = (slot, place) => {
    if (!slot.from_link) {
      slot.from_link = true
      slot.link_place = place.name
      slot.link_places = []
      if (place.quote) slot.link_quote = place.quote
      if (place.note) slot.link_note = place.note
    }
    slot.link_places.push(place.name)
  }
  const scheduled = []
  const extras = []
  const missing = []

  let pending = [...places]
  for (const field of ['activity', 'location']) {
    const still = []
    for (const place of pending) {
      let hit = null
      for (const day of days) {
        if (!rightCity(day, place)) continue
        // Travel slots may name a place by their activity ("Train to Sintra
        // for Pena Palace"); arrival/hotel logistics never do
        const slot = slotsOf(day).find((s) => !isArrivalSlot(s) && (field === 'activity' || !logistics(s))
          && sameLinkPlace(place.name, s[field]) && (field === 'activity' || !s.from_link))
        if (slot) { hit = [day, slot]; break }
      }
      if (hit) {
        mark(hit[1], place)
        bump(hit[0])
        scheduled.push(place.name)
      } else {
        still.push(place)
      }
    }
    pending = still
  }

  let removedCost = 0
  const isNumber = (v) => typeof v === 'number' && Number.isFinite(v)
  // Slots first, transport notes after, so notes land the same on every pass
  pending.sort((a, b) => (a.kind === 'transport') - (b.kind === 'transport'))
  for (const place of pending) {
    const inCity = multi && place.city ? days.filter((d) => !dayCity(d) || cityKey(dayCity(d)) === cityKey(place.city)) : days
    const candidates = inCity.length ? inCity : days
    const inner = candidates.filter((d) => ![0, last].includes(days.indexOf(d)) && !travelIn.has(d))
    const innerOrEnds = inner.length ? inner : candidates.filter((d) => ![0, last].includes(days.indexOf(d)))
    const poolOf = (list) => list.flatMap((day) => slotsOf(day).filter((s) => !s.from_link && !logistics(s)).map((s) => [day, s]))
    // A transport place ("Tram 28") never takes a slot: unmatched, it's a note
    const pool = place.kind === 'transport' ? [] : (poolOf(innerOrEnds).length ? poolOf(innerOrEnds) : poolOf(candidates))
    if (pool.length) {
      const rank = ([day, slot]) => {
        const free = FREE_TIME.test(slot.activity || '')
        const tod = String(slot.time_of_day || '').toLowerCase()
        const fits = ['afternoon', 'evening'].includes(tod) === MEAL_KINDS.has(place.kind)
        return [free ? 0 : 1, fits ? 0 : 1, linkedPerDay.get(day) || 0, slot.duration_hours || 0]
      }
      const cmp = (a, b) => { for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return a[i] - b[i]; return 0 }
      const [day, slot] = pool.reduce((best, cur) => (cmp(rank(cur), rank(best)) < 0 ? cur : best))
      const where = place.town || place.city || searchData.destination
      slot.activity = place.note ? `${place.name} — ${place.note}` : place.name
      slot.location = `${place.name}, ${where}`
      slot.duration_hours = DURATION[place.kind] ?? 2
      if (isNumber(slot.estimated_cost_usd)) {
        if (isNumber(day.daily_estimated_cost_usd)) day.daily_estimated_cost_usd = Math.max(0, Math.round((day.daily_estimated_cost_usd - slot.estimated_cost_usd) * 100) / 100)
        removedCost += slot.estimated_cost_usd
      }
      for (const key of STALE_FIELDS) delete slot[key]
      slot.estimated_cost_usd = null
      if (place.lat != null && place.lng != null) { slot.lat = place.lat; slot.lng = place.lng }
      mark(slot, place)
      bump(day)
      scheduled.push(place.name)
    } else if (innerOrEnds.length || candidates.length) {
      const list = innerOrEnds.length ? innerOrEnds : candidates
      const day = list.reduce((best, d) => ((linkedPerDay.get(d) || 0) < (linkedPerDay.get(best) || 0) ? d : best))
      ;(day.link_extras ||= []).push({ name: place.name, note: place.note || null, quote: place.quote || null })
      bump(day)
      extras.push(place.name)
    } else {
      missing.push(place.name)
    }
  }

  if (removedCost && isNumber(out.total_estimated_cost_usd)) {
    out.total_estimated_cost_usd = Math.max(0, Math.round((out.total_estimated_cost_usd - removedCost) * 100) / 100)
  }
  out.link_coverage = { total: places.length, scheduled, extras, missing }
  return out
}
