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
const tokens = (text) => foldText(text).split(/[^a-z0-9]+/).filter(Boolean)
const nameTokens = (name) => tokens(name).filter((t) => !NAME_FILLER.has(t))
const cityKey = (text) => foldText(String(text || '').split(',')[0]).trim()

/** `text` names the place: every token of its name, as whole tokens. */
export function sameLinkPlace(name, text) {
  const wanted = nameTokens(name)
  if (!wanted.length) return false
  const have = new Set(tokens(text))
  if (wanted.every((t) => have.has(t))) return true
  const joined = wanted.join('')
  return joined.length >= 8 && tokens(text).join('').includes(joined)
}

/** Travel and hotel logistics, which are never replaced or matched. */
export function isLogisticsSlot(slot, stopCities = []) {
  const kind = String(slot?.category || slot?.type || '').trim().toLowerCase()
  if (LOGISTICS_TYPES.has(kind)) return true
  const text = String(slot?.activity || '')
  if (LOGISTICS.test(text)) return true
  const folded = foldText(text)
  return stopCities.some((c) => {
    const key = cityKey(c)
    return key && new RegExp(`\\bto ${key.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\b`).test(folded)
  })
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
  const rightCity = (day, place) => !(multi && place.city && day.city) || cityKey(day.city) === cityKey(place.city)
  const travelIn = new Set(days.filter((d, i) => i > 0 && d.city && cityKey(d.city) !== cityKey(days[i - 1].city)))

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
        const slot = slotsOf(day).find((s) => !logistics(s) && sameLinkPlace(place.name, s[field])
          && (field === 'activity' || !s.from_link))
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

  for (const place of pending) {
    const inCity = multi && place.city ? days.filter((d) => !d.city || cityKey(d.city) === cityKey(place.city)) : days
    const candidates = inCity.length ? inCity : days
    const inner = candidates.filter((d) => ![0, last].includes(days.indexOf(d)) && !travelIn.has(d))
    const innerOrEnds = inner.length ? inner : candidates.filter((d) => ![0, last].includes(days.indexOf(d)))
    const poolOf = (list) => list.flatMap((day) => slotsOf(day).filter((s) => !s.from_link && !logistics(s)).map((s) => [day, s]))
    const pool = poolOf(innerOrEnds).length ? poolOf(innerOrEnds) : poolOf(candidates)
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

  out.link_coverage = { total: places.length, scheduled, extras, missing }
  return out
}
