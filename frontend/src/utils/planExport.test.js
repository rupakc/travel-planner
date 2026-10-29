// @vitest-environment node
import { describe, it, expect } from 'vitest'
import { buildPlanIcs, icsEscape, icsFold, planItineraryDays } from './planExport'
import { moveSlot, removeSlot } from './itineraryLayout'

const NOW = new Date(Date.UTC(2026, 9, 28, 12, 0, 0))

const searchData = {
  origin: 'New York, USA (JFK)',
  destination: 'Tokyo, Japan (HND)',
  departure_date: '2027-04-01',
  return_date: '2027-04-04',
}

const itinerary = {
  days: [
    {
      day_number: 1, date: '2027-04-01', city: 'Tokyo', theme: 'Arrival',
      slots: [
        { time_of_day: 'morning', activity: 'Tsukiji Outer Market', location: 'Tsukiji, Tokyo', duration_hours: 2, estimated_cost_usd: 40 },
        { time_of_day: 'evening', activity: 'Shibuya Crossing', location: 'Shibuya' },
      ],
    },
    {
      day_number: 2, slots: [{ time_of_day: 'afternoon', activity: 'Meiji Shrine' }],
    },
  ],
}

// Unfold continuation lines and split into content lines
const lines = (ics) => ics.replace(/\r\n[ \t]/g, '').split('\r\n')
const events = (ics) => ics.split('BEGIN:VEVENT').slice(1).map((e) => lines('BEGIN:VEVENT' + e.split('END:VEVENT')[0]))
const field = (event, name) => event.find((l) => l.startsWith(name + ':') || l.startsWith(name + ';'))

describe('icsEscape', () => {
  it('escapes backslashes, semicolons, commas and newlines', () => {
    expect(icsEscape('a\\b;c,d\ne')).toBe('a\\\\b\\;c\\,d\\ne')
  })

  it('treats CRLF and a lone CR as newlines and drops control characters', () => {
    expect(icsEscape('a\r\nb\rc')).toBe('a\\nb\\nc')
    expect(icsEscape('a\u0000b\u0007c\u007fd\te')).toBe('abcd\te')
  })
})

describe('icsFold', () => {
  it('leaves short lines alone', () => {
    expect(icsFold('SUMMARY:Short')).toBe('SUMMARY:Short')
  })

  it('folds lines over 75 octets with CRLF + space', () => {
    const folded = icsFold('DESCRIPTION:' + 'x'.repeat(200))
    const parts = folded.split('\r\n')
    expect(parts.length).toBeGreaterThan(1)
    parts.forEach((p) => expect(new TextEncoder().encode(p).length).toBeLessThanOrEqual(75))
    expect(parts.slice(1).every((p) => p.startsWith(' '))).toBe(true)
    expect(folded.replace(/\r\n /g, '')).toBe('DESCRIPTION:' + 'x'.repeat(200))
  })

  it('never splits a multi-byte character', () => {
    const folded = icsFold('SUMMARY:' + '東京'.repeat(40))
    expect(folded.replace(/\r\n /g, '')).toBe('SUMMARY:' + '東京'.repeat(40))
    folded.split('\r\n').forEach((p) => expect(new TextEncoder().encode(p).length).toBeLessThanOrEqual(75))
  })
})

describe('planItineraryDays', () => {
  it('prefers the full itinerary, then the saved snapshot', () => {
    expect(planItineraryDays({}, itinerary)).toBe(itinerary.days)
    expect(planItineraryDays({ itinerary }, null)).toBe(itinerary.days)
  })

  it('falls back to individually selected slots grouped by day', () => {
    const sel = {
      itinerary_slots: [
        { key: '2-afternoon', day_number: 2, time_of_day: 'afternoon', activity: 'B' },
        { key: '1-morning', day_number: 1, time_of_day: 'morning', activity: 'A', date: '2027-04-01' },
      ],
    }
    const days = planItineraryDays(sel, null)
    expect(days.map((d) => d.day_number)).toEqual([1, 2])
    expect(days[0].slots[0].activity).toBe('A')
  })

  it('is empty when there is no itinerary', () => {
    expect(planItineraryDays({}, null)).toEqual([])
  })
})

describe('buildPlanIcs', () => {
  const build = (selections = {}, extra = {}) =>
    buildPlanIcs({ planName: 'Tokyo Trip', searchData, selections, itinerary, now: NOW, ...extra })

  it('is a valid calendar wrapper with CRLF line endings', () => {
    const ics = build()
    expect(ics.startsWith('BEGIN:VCALENDAR\r\nVERSION:2.0\r\n')).toBe(true)
    expect(ics.endsWith('END:VCALENDAR\r\n')).toBe(true)
    expect(ics).toContain('PRODID:')
    expect(ics).toContain('X-WR-CALNAME:Tokyo Trip')
    expect(ics.replace(/\r\n/g, '')).not.toMatch(/\n/)
  })

  it('makes one timed event per itinerary slot on its date', () => {
    const evs = events(build())
    expect(evs).toHaveLength(3)
    const [market, crossing, shrine] = evs
    expect(field(market, 'SUMMARY')).toBe('SUMMARY:Tsukiji Outer Market')
    expect(field(market, 'DTSTART')).toBe('DTSTART:20270401T090000')
    expect(field(market, 'DTEND')).toBe('DTEND:20270401T110000')
    expect(field(market, 'LOCATION')).toBe('LOCATION:Tsukiji\\, Tokyo')
    expect(field(crossing, 'DTSTART')).toBe('DTSTART:20270401T180000')
    expect(field(crossing, 'DTEND')).toBe('DTEND:20270401T210000')
    // Day 2 has no date: derived from the trip's departure date
    expect(field(shrine, 'DTSTART')).toBe('DTSTART:20270402T130000')
  })

  it('applies the user\'s slot edits and notes', () => {
    const evs = events(build({
      itinerary_edits: { '1-morning': { activity: 'Toyosu Market', location: 'Toyosu' } },
      itinerary_notes: { '1-morning': 'Go early; tuna auction' },
    }))
    expect(field(evs[0], 'SUMMARY')).toBe('SUMMARY:Toyosu Market')
    expect(field(evs[0], 'LOCATION')).toBe('LOCATION:Toyosu')
    expect(field(evs[0], 'DESCRIPTION')).toContain('Go early\\; tuna auction')
  })

  it('every event has a unique UID and a DTSTAMP', () => {
    const evs = events(build({ hotel: { name: 'Park Hyatt Tokyo' } }))
    const uids = evs.map((e) => field(e, 'UID'))
    expect(new Set(uids).size).toBe(evs.length)
    evs.forEach((e) => expect(field(e, 'DTSTAMP')).toBe('DTSTAMP:20261028T120000Z'))
  })

  it('adds the hotel stay as an all-day span ending on check-out', () => {
    const evs = events(build({ hotel: { name: 'Park Hyatt Tokyo', location: 'Shinjuku' } }))
    const hotel = evs.find((e) => field(e, 'SUMMARY').includes('Park Hyatt'))
    expect(field(hotel, 'DTSTART')).toBe('DTSTART;VALUE=DATE:20270401')
    expect(field(hotel, 'DTEND')).toBe('DTEND;VALUE=DATE:20270404')
  })

  it('adds a timed flight using its departure time and duration', () => {
    const flight = {
      price_usd: 900,
      outbound: { airline: 'ANA', flight_number: 'NH9', origin: 'JFK', destination: 'HND', departure_date: '2027-04-01', departure_time: '11:55', duration_minutes: 840 },
      return: { airline: 'ANA', flight_number: 'NH10', origin: 'HND', destination: 'JFK', departure_time: '17:05' },
    }
    const evs = events(build({ flight }))
    const out = evs.find((e) => field(e, 'SUMMARY').includes('NH9'))
    expect(field(out, 'SUMMARY')).toBe('SUMMARY:✈ ANA NH9 JFK → HND')
    expect(field(out, 'DTSTART')).toBe('DTSTART:20270401T115500')
    expect(field(out, 'DTEND')).toBe('DTEND:20270402T015500')
    // Return leg without its own date departs on the trip's return date
    const ret = evs.find((e) => field(e, 'SUMMARY').includes('NH10'))
    expect(field(ret, 'DTSTART')).toBe('DTSTART:20270404T170500')
  })

  it('makes an all-day flight event when the time is unknown', () => {
    const evs = events(build({ flights: [{ leg_index: 0, leg_date: '2027-04-01', leg_from: 'New York', leg_to: 'Seoul', outbound: { airline: 'KE', flight_number: 'KE82' } }] }))
    const leg = evs.find((e) => field(e, 'SUMMARY').includes('KE82'))
    expect(field(leg, 'DTSTART')).toBe('DTSTART;VALUE=DATE:20270401')
    expect(field(leg, 'DTEND')).toBe('DTEND;VALUE=DATE:20270402')
  })

  it('adds selected local events as all-day events over their dates', () => {
    const evs = events(build({ events: [
      { name: 'Sumida River Fireworks', start_date: '2027-04-02', end_date: '2027-04-03', location: 'Asakusa' },
      { name: 'Undated meetup' },
    ] }))
    const fireworks = evs.find((e) => field(e, 'SUMMARY').includes('Sumida'))
    expect(field(fireworks, 'DTSTART')).toBe('DTSTART;VALUE=DATE:20270402')
    expect(field(fireworks, 'DTEND')).toBe('DTEND;VALUE=DATE:20270404')
    expect(evs.some((e) => field(e, 'SUMMARY').includes('Undated'))).toBe(false)
  })

  const uids = (ics) => events(ics).map((e) => field(e, 'UID'))

  it('gives different plans different event IDs even with the same name', () => {
    const a = build({ hotel: { name: 'H' } }, { planName: 'My Trip Plan', planId: 1 })
    const b = build({ hotel: { name: 'H' } }, { planName: 'My Trip Plan', planId: 2 })
    expect(uids(a).some((u) => uids(b).includes(u))).toBe(false)
  })

  it('keeps a saved plan\'s event IDs when it is renamed', () => {
    const a = build({ hotel: { name: 'H' } }, { planName: 'Japan', planId: 7 })
    const b = build({ hotel: { name: 'H' } }, { planName: 'Japan 2027', planId: 7 })
    expect(uids(a)).toEqual(uids(b))
  })

  it('tells unsaved trips apart by their route and dates, not just the name', () => {
    const tokyo = build({ hotel: { name: 'H' } }, { planName: '東京' })
    const paris = build({ hotel: { name: 'H' } }, { planName: '東京', searchData: { ...searchData, destination: 'Paris' } })
    expect(uids(tokyo).some((u) => uids(paris).includes(u))).toBe(false)
  })

  it('keeps a local event\'s ID when another event is removed', () => {
    const sumida = { name: 'Sumida', start_date: '2027-04-02' }
    const both = build({ events: [{ name: 'Other', start_date: '2027-04-01' }, sumida] })
    const one = build({ events: [sumida] })
    const sumidaUid = (ics) => events(ics).find((e) => field(e, 'SUMMARY').includes('Sumida')).find((l) => l.startsWith('UID'))
    expect(sumidaUid(both)).toBe(sumidaUid(one))
  })

  it('puts the local arrival time and booking link in a flight\'s description', () => {
    const flight = {
      booking_url: 'https://example.com/book',
      outbound: { airline: 'ANA', flight_number: 'NH9', departure_date: '2027-04-01', departure_time: '11:55', arrival_time: '15:55', duration_minutes: 840 },
    }
    const out = events(build({ flight })).find((e) => field(e, 'SUMMARY').includes('NH9'))
    expect(field(out, 'DESCRIPTION')).toContain('Arrives 15:55 local time')
    expect(field(out, 'DESCRIPTION')).toContain('https://example.com/book')
  })

  it('includes the itinerary\'s own slot notes', () => {
    const ics = build({}, { itinerary: { days: [{ day_number: 1, date: '2027-04-01', slots: [{ time_of_day: 'morning', activity: 'A', notes: 'Closed Mondays' }] }] } })
    expect(field(events(ics)[0], 'DESCRIPTION')).toContain('Closed Mondays')
  })

  it('lets a long evening slot run past midnight', () => {
    const ics = build({}, { itinerary: { days: [{ day_number: 1, date: '2027-04-01', slots: [{ time_of_day: 'evening', activity: 'Night tour', duration_hours: 8 }] }] } })
    expect(field(events(ics)[0], 'DTEND')).toBe('DTEND:20270402T020000')
  })

  it('gives a same-day trip\'s hotel a single night', () => {
    const ics = build({ hotel: { name: 'H' } }, { searchData: { ...searchData, return_date: '2027-04-01' } })
    const hotel = events(ics).find((e) => field(e, 'SUMMARY').includes('H'))
    expect(field(hotel, 'DTEND')).toBe('DTEND;VALUE=DATE:20270402')
  })

  it('skips events it cannot date', () => {
    const ics = buildPlanIcs({
      planName: 'No dates', searchData: {}, now: NOW,
      selections: {}, itinerary: { days: [{ day_number: 1, slots: [{ time_of_day: 'morning', activity: 'X' }] }] },
    })
    expect(events(ics)).toHaveLength(0)
  })
})

describe('arranged itinerary', () => {
  const trip = {
    days: [
      { day_number: 1, date: '2027-04-01', city: 'Tokyo', theme: 'Arrival', slots: [
        { time_of_day: 'morning', activity: 'Tsukiji Outer Market', location: 'Tsukiji', estimated_cost_usd: 40 },
        { time_of_day: 'evening', activity: 'Shibuya Crossing' },
      ] },
      { day_number: 2, date: '2027-04-02', city: 'Tokyo', theme: 'Culture', slots: [
        { time_of_day: 'morning', activity: 'Meiji Shrine' },
        { time_of_day: 'evening', activity: 'Izakaya crawl' },
      ] },
    ],
  }
  const swapped = moveSlot(trip, null, '1-morning', 2, 'evening')
  const removed = removeSlot(trip, null, '1-morning')
  const sel = {
    itinerary_layout: swapped,
    itinerary_edits: { '1-morning': { activity: 'Toyosu Market' } },
    itinerary_notes: { '1-morning': 'Go early' },
  }
  const build = (selections, it = trip) => buildPlanIcs({ planName: 'T', searchData, selections, itinerary: it, now: NOW })

  it('planItineraryDays applies the layout to the live itinerary and the snapshot', () => {
    const days = planItineraryDays(sel, trip)
    expect(days[1].slots.map((x) => x.activity)).toEqual(['Meiji Shrine', 'Tsukiji Outer Market'])
    expect(days[0].slots.map((x) => x.activity)).toEqual(['Izakaya crawl', 'Shibuya Crossing'])
    expect(planItineraryDays({ ...sel, itinerary: trip }, null)[1].slots[1].activity).toBe('Tsukiji Outer Market')
  })

  it('does not rearrange the itinerary_slots fallback', () => {
    const slots = [{ day_number: 1, date: '2027-04-01', time_of_day: 'morning', activity: 'X' }]
    const days = planItineraryDays({ itinerary_layout: swapped, itinerary_slots: slots }, null)
    expect(days[0].slots[0].activity).toBe('X')
  })

  it('moves the .ics event with its UID, edit and note', () => {
    const evs = events(build(sel))
    const moved = evs.find((e) => field(e, 'UID').includes('slot-1-morning'))
    expect(field(moved, 'SUMMARY')).toBe('SUMMARY:Toyosu Market')
    expect(field(moved, 'DTSTART')).toBe('DTSTART:20270402T180000')
    expect(field(moved, 'DTEND')).toBe('DTEND:20270402T210000')
    expect(field(moved, 'DESCRIPTION')).toContain('Go early')
    const partner = evs.find((e) => field(e, 'SUMMARY') === 'SUMMARY:Izakaya crawl')
    expect(field(partner, 'DTSTART')).toBe('DTSTART:20270401T090000')
  })

  it('a removed activity produces no event', () => {
    const evs = events(build({ itinerary_layout: removed }))
    expect(evs).toHaveLength(3)
    expect(evs.some((e) => field(e, 'SUMMARY') === 'SUMMARY:Tsukiji Outer Market')).toBe(false)
  })

  it('a layout from another itinerary is ignored', () => {
    const other = { days: [{ day_number: 1, date: '2027-04-01', slots: [{ time_of_day: 'morning', activity: 'Other' }] }] }
    expect(planItineraryDays({ itinerary_layout: swapped }, other)).toBe(other.days)
  })
})
