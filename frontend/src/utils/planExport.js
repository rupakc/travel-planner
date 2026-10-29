import { arrangeItinerary, slotKey } from './itineraryLayout'
import { EARLIEST_START, scheduleDays } from './schedule'

// Plan export: an iCalendar (.ics, RFC 5545) file of the trip, built from
// the same selections the My Plan drawer shows.
//
// Times are "floating" (no time zone): a 09:00 museum visit in Tokyo should
// read 09:00 in the traveller's calendar wherever it is opened.

const SLOT_HOURS = {
  morning: { start: 9, end: 12 },
  afternoon: { start: 13, end: 17 },
  evening: { start: 18, end: 21 },
}
const SLOT_ORDER = ['morning', 'afternoon', 'evening']

const pad = (n) => String(n).padStart(2, '0')
// "HH:MM" -> minutes past midnight, or null
const clockMinutes = (hhmm) => {
  const m = /^(\d{2}):(\d{2})$/.exec(hhmm || '')
  return m ? Number(m[1]) * 60 + Number(m[2]) : null
}
const isIsoDate = (s) => typeof s === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(s)

// Date-only arithmetic in UTC so daylight-saving changes can't skew it
const addDays = (iso, days) => {
  const [y, m, d] = iso.split('-').map(Number)
  return new Date(Date.UTC(y, m - 1, d + days)).toISOString().slice(0, 10)
}
const icsDate = (iso) => iso.replace(/-/g, '')
// Floating local date-time: minutes past midnight of `iso`, may roll over days
const icsDateTime = (iso, minutes) => {
  const dayOffset = Math.floor(minutes / 1440)
  const m = minutes - dayOffset * 1440
  return `${icsDate(addDays(iso, dayOffset))}T${pad(Math.floor(m / 60))}${pad(m % 60)}00`
}
const icsStamp = (date) => date.toISOString().replace(/[-:]/g, '').replace(/\.\d{3}/, '')

/** Escape a TEXT value (RFC 5545 §3.3.11). */
export function icsEscape(text) {
  return String(text)
    // Control characters aren't allowed in TEXT (tab is)
    .replace(/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/g, '')
    .replace(/\\/g, '\\\\')
    .replace(/;/g, '\\;')
    .replace(/,/g, '\\,')
    .replace(/\r\n|\r|\n/g, '\\n')
}

/** Fold a content line to at most 75 octets per line (RFC 5545 §3.1). */
export function icsFold(line) {
  const encoder = new TextEncoder()
  if (encoder.encode(line).length <= 75) return line
  const out = []
  let current = ''
  let bytes = 0
  for (const ch of line) {
    const size = encoder.encode(ch).length
    // Continuation lines start with a space, which counts toward the 75
    const limit = out.length === 0 ? 75 : 74
    if (bytes + size > limit) {
      out.push(current)
      current = ''
      bytes = 0
    }
    current += ch
    bytes += size
  }
  out.push(current)
  return out.join('\r\n ')
}

// "11:55", "9:05", "11:55 PM" → minutes past midnight, or null
function parseTime(value) {
  const m = /^\s*(\d{1,2}):(\d{2})\s*(am|pm)?/i.exec(value || '')
  if (!m) return null
  let h = Number(m[1])
  const min = Number(m[2])
  const meridiem = m[3]?.toLowerCase()
  if (meridiem === 'pm' && h < 12) h += 12
  if (meridiem === 'am' && h === 12) h = 0
  if (h > 23 || min > 59) return null
  return h * 60 + min
}

// FNV-1a: a short, stable fingerprint for event IDs (not for security)
function fingerprint(text) {
  let h = 0x811c9dc5
  for (const ch of String(text)) {
    h ^= ch.codePointAt(0)
    h = Math.imul(h, 0x01000193) >>> 0
  }
  return h.toString(36)
}

const shortPlace = (place) => (place || '').split(',')[0].trim()

/**
 * The plan's day-by-day itinerary: the live one if given, else the snapshot
 * saved with the plan — arranged by the user's layout and given estimated
 * times (see scheduleDays) — else the individually selected slots grouped by
 * day, which carry no times.
 */
export function planItineraryDays(selections, itinerary) {
  const arranged = (source) => {
    const edits = selections?.itinerary_edits || {}
    return scheduleDays(arrangeItinerary(source, selections?.itinerary_layout, edits).days, edits)
  }
  if (itinerary?.days?.length) return arranged(itinerary)
  if (selections?.itinerary?.days?.length) return arranged(selections.itinerary)
  const byDay = new Map()
  for (const slot of selections?.itinerary_slots || []) {
    if (!byDay.has(slot.day_number)) byDay.set(slot.day_number, { day_number: slot.day_number, date: slot.date, slots: [] })
    byDay.get(slot.day_number).slots.push(slot)
  }
  return [...byDay.values()]
    .sort((a, b) => a.day_number - b.day_number)
    .map((d) => ({ ...d, slots: d.slots.sort((a, b) => SLOT_ORDER.indexOf(a.time_of_day) - SLOT_ORDER.indexOf(b.time_of_day)) }))
}

function dayDate(day, searchData) {
  if (isIsoDate(day.date)) return day.date
  if (isIsoDate(searchData?.departure_date) && day.day_number >= 1) {
    return addDays(searchData.departure_date, day.day_number - 1)
  }
  return null
}

function itineraryEvents(days, selections, searchData) {
  const events = []
  for (const day of days) {
    const date = dayDate(day, searchData)
    if (!date) continue
    for (const slot of day.slots || []) {
      const key = slot.key ?? slotKey(day.day_number, slot.time_of_day)
      const edit = selections?.itinerary_edits?.[key] || {}
      const note = selections?.itinerary_notes?.[key]
      let start = clockMinutes(slot.start_time)
      let end = clockMinutes(slot.end_time)
      if (start != null && end != null) {
        // Clock times wrap at midnight. A day's schedule never starts before
        // EARLIEST_START, so an earlier clock time is past midnight.
        if (start < EARLIEST_START) start += 1440
        while (end <= start) end += 1440
      } else {
        const hours = SLOT_HOURS[slot.time_of_day] || SLOT_HOURS.morning
        start = hours.start * 60
        end = slot.duration_hours > 0 ? start + Math.round(slot.duration_hours * 60) : hours.end * 60
      }
      const cost = edit.cost ?? slot.estimated_cost_usd
      const description = [
        day.theme && `Day ${day.day_number}: ${day.theme}`,
        slot.notes,
        note,
        cost > 0 && `Est. cost: $${Number(cost).toLocaleString('en-US')}`,
      ].filter(Boolean).join('\n')
      events.push({
        id: `slot-${key}`,
        summary: edit.activity ?? slot.activity,
        location: edit.location ?? slot.location ?? day.city,
        description,
        start: icsDateTime(date, start),
        end: icsDateTime(date, end),
      })
    }
  }
  return events
}

function flightEvent(id, leg, date, fallback = {}, bookingUrl = null) {
  if (!leg || !isIsoDate(date)) return null
  const from = leg.origin || shortPlace(fallback.from)
  const to = leg.destination || shortPlace(fallback.to)
  const summary = ['✈', leg.airline, leg.flight_number, from && to ? `${from} → ${to}` : ''].filter(Boolean).join(' ')
  // Floating times follow the departure clock, so the arrival — in the
  // destination's clock — is spelled out instead
  const description = [
    leg.arrival_time && `Arrives ${leg.arrival_time} local time`,
    bookingUrl && `Booking: ${bookingUrl}`,
  ].filter(Boolean).join('\n')
  const departs = parseTime(leg.departure_time)
  if (departs == null) {
    return { id, summary, description, allDay: true, start: icsDate(date), end: icsDate(addDays(date, 1)) }
  }
  return {
    id,
    summary,
    description,
    start: icsDateTime(date, departs),
    end: leg.duration_minutes > 0 ? icsDateTime(date, departs + leg.duration_minutes) : null,
  }
}

function flightEvents(selections, searchData) {
  const events = []
  const f = selections?.flight
  if (f) {
    const out = f.outbound || f
    events.push(flightEvent('flight-out', out, out.departure_date || searchData?.departure_date, {}, f.booking_url))
    if (f.return) events.push(flightEvent('flight-return', f.return, f.return.departure_date || searchData?.return_date, {}, f.booking_url))
  }
  ;(selections?.flights || []).forEach((leg, i) => {
    const out = leg.outbound || leg
    events.push(flightEvent(`flight-leg-${leg.leg_index ?? i}`, out, out.departure_date || leg.leg_date, { from: leg.leg_from, to: leg.leg_to }, leg.booking_url))
  })
  return events.filter(Boolean)
}

function hotelEvent(hotel, searchData) {
  const checkIn = searchData?.departure_date
  if (!hotel?.name || !isIsoDate(checkIn)) return null
  const checkOut = isIsoDate(searchData?.return_date) && searchData.return_date > checkIn
    ? searchData.return_date
    : addDays(checkIn, 1)
  return {
    id: 'hotel',
    summary: `🏨 ${hotel.name}`,
    location: hotel.location,
    description: hotel.booking_url ? `Booking: ${hotel.booking_url}` : '',
    allDay: true,
    start: icsDate(checkIn),
    end: icsDate(checkOut),
  }
}

function localEvents(events) {
  return (events || [])
    .filter((ev) => ev?.name && isIsoDate(ev.start_date))
    .map((ev) => {
      const last = isIsoDate(ev.end_date) && ev.end_date >= ev.start_date ? ev.end_date : ev.start_date
      return {
        id: `event-${fingerprint(`${ev.name}|${ev.start_date}`)}`,
        summary: `🎉 ${ev.name}`,
        location: ev.location,
        description: [ev.description, ev.price && `Price: ${ev.price}`].filter(Boolean).join('\n'),
        allDay: true,
        start: icsDate(ev.start_date),
        // All-day DTEND is exclusive: the day after the last day
        end: icsDate(addDays(last, 1)),
      }
    })
}

const slug = (s) => (s || 'trip').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'trip'

// Event IDs must differ between plans (calendar apps merge events that
// share a UID) yet survive a rename: a saved plan's id is ideal; an unsaved
// plan falls back to its route, dates and name.
function uidBase(planId, planName, searchData) {
  if (planId != null) return `plan-${planId}`
  const trip = [searchData?.origin, searchData?.destination, searchData?.departure_date, searchData?.return_date, planName]
  return `trip-${slug(planName)}-${fingerprint(trip.join('|'))}`
}

/**
 * Build the .ics text for a plan. `itinerary` is the live itinerary when the
 * plan comes straight from a search; saved plans carry their own snapshot.
 * `planId` is the saved plan's id, when there is one.
 */
export function buildPlanIcs({ planName, searchData, selections, itinerary = null, planId = null, now = new Date() }) {
  const events = [
    ...flightEvents(selections, searchData),
    hotelEvent(selections?.hotel, searchData),
    ...localEvents(selections?.events),
    ...itineraryEvents(planItineraryDays(selections, itinerary), selections, searchData),
  ].filter(Boolean)

  const stamp = icsStamp(now)
  const base = uidBase(planId, planName, searchData)
  const lines = [
    'BEGIN:VCALENDAR',
    'VERSION:2.0',
    'PRODID:-//Voyager Travel Planner//Plan Export//EN',
    'CALSCALE:GREGORIAN',
    'METHOD:PUBLISH',
    `X-WR-CALNAME:${icsEscape(planName || 'Trip plan')}`,
  ]
  for (const ev of events) {
    const dateParam = ev.allDay ? ';VALUE=DATE' : ''
    lines.push(
      'BEGIN:VEVENT',
      // Stable per plan + item, so re-importing updates rather than duplicates
      `UID:${base}-${ev.id}@voyager-travel-planner`,
      `DTSTAMP:${stamp}`,
      `DTSTART${dateParam}:${ev.start}`,
      ...(ev.end ? [`DTEND${dateParam}:${ev.end}`] : []),
      `SUMMARY:${icsEscape(ev.summary || 'Trip')}`,
      ...(ev.location ? [`LOCATION:${icsEscape(ev.location)}`] : []),
      ...(ev.description ? [`DESCRIPTION:${icsEscape(ev.description)}`] : []),
      'END:VEVENT',
    )
  }
  lines.push('END:VCALENDAR')
  return lines.map(icsFold).join('\r\n') + '\r\n'
}

/** A safe download file name for the plan, e.g. "tokyo-trip.ics". */
export function planFileName(planName, ext) {
  return `${slug(planName)}.${ext}`
}
