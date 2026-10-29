// @vitest-environment node
import { describe, it, expect } from 'vitest'
import { createHash } from 'node:crypto'
import { buildPlanPrintHtml, escapeHtml, safeUrl } from './planPrint'
import { moveSlot, removeSlot } from './itineraryLayout'

const searchData = {
  origin: 'New York, USA (JFK)',
  destination: 'Tokyo, Japan (HND)',
  departure_date: '2027-04-01',
  return_date: '2027-04-04',
  num_travelers: 2,
  budget_usd: 3000,
}

const itinerary = {
  days: [{
    day_number: 1, date: '2027-04-01', theme: 'Arrival', city: 'Tokyo',
    slots: [{ time_of_day: 'morning', activity: 'Tsukiji Outer Market', location: 'Tsukiji', estimated_cost_usd: 40 }],
  }],
}

const selections = {
  flight: { price_usd: 900, outbound: { airline: 'ANA', flight_number: 'NH9', origin: 'JFK', destination: 'HND', departure_time: '11:55' } },
  hotel: { name: 'Park Hyatt Tokyo', location: 'Shinjuku', price_per_night_usd: 620, total_price_usd: 1860, booking_url: 'https://example.com/hotel' },
  activities: [{ name: 'Sushi class', price_usd: 120, booking_url: 'javascript:alert(1)' }],
  sim: { provider: 'Ubigi', plan_name: '10GB', price_usd: 25 },
  getting_around: [{ name: 'Suica card', price_info: '¥1,000 deposit' }],
  tips: [{ title: 'Carry cash', body: 'Many small shops are cash only.' }],
}

const build = (overrides = {}) =>
  buildPlanPrintHtml({ planName: 'Tokyo Trip', searchData, selections, itinerary, ...overrides })

describe('escapeHtml', () => {
  it('escapes the HTML special characters', () => {
    expect(escapeHtml(`<a href="x">'&'</a>`)).toBe('&lt;a href=&quot;x&quot;&gt;&#39;&amp;&#39;&lt;/a&gt;')
  })

  it('renders null and undefined as empty', () => {
    expect(escapeHtml(null)).toBe('')
    expect(escapeHtml(undefined)).toBe('')
  })
})

describe('safeUrl', () => {
  it('keeps http and https links', () => {
    expect(safeUrl('https://example.com/a?b=1')).toBe('https://example.com/a?b=1')
    expect(safeUrl('http://example.com')).toBe('http://example.com/')
  })

  it('drops script and other non-web links', () => {
    expect(safeUrl('javascript:alert(1)')).toBeNull()
    expect(safeUrl('data:text/html,hi')).toBeNull()
    expect(safeUrl('not a url')).toBeNull()
    expect(safeUrl(undefined)).toBeNull()
  })
})

describe('buildPlanPrintHtml', () => {
  it('is a complete document titled with the plan name', () => {
    const html = build()
    expect(html.startsWith('<!doctype html>')).toBe(true)
    expect(html).toContain('<meta charset="utf-8">')
    expect(html).toContain('<title>Tokyo Trip</title>')
  })

  it('shows the trip summary', () => {
    const html = build()
    expect(html).toContain('New York → Tokyo')
    expect(html).toContain('Apr 1 – Apr 4, 2027')
    expect(html).toContain('2 travelers')
  })

  it('includes the cost breakdown with a total that matches its parts', () => {
    const html = build()
    expect(html).toContain('Where the money goes')
    expect(html).toContain('$1,860')
    expect(html).toContain('$900')
    // 1860 + 900 + 120 + 25
    expect(html).toContain('$2,905')
    expect(html).toContain('Budget: $3,000')
  })

  it('lists every selected section', () => {
    const html = build()
    for (const text of ['ANA NH9', 'Park Hyatt Tokyo', 'Sushi class', 'Ubigi', 'Suica card', 'Carry cash', 'Tsukiji Outer Market']) {
      expect(html).toContain(text)
    }
  })

  it('leaves out sections with nothing selected', () => {
    const html = build({ selections: { hotel: selections.hotel }, itinerary: null })
    expect(html).toContain('Park Hyatt Tokyo')
    expect(html).not.toContain('<h2>Flights')
    expect(html).not.toContain('<h2>Itinerary')
    expect(html).not.toContain('<h2>Tips')
  })

  it('applies itinerary edits and notes', () => {
    const html = build({
      selections: {
        ...selections,
        itinerary_edits: { '1-morning': { activity: 'Toyosu Market' } },
        itinerary_notes: { '1-morning': 'Go early' },
      },
    })
    expect(html).toContain('Toyosu Market')
    expect(html).not.toContain('Tsukiji Outer Market')
    expect(html).toContain('Go early')
  })

  it('escapes content so plan text can never inject markup or script', () => {
    const html = build({
      planName: '<script>alert(1)</script>',
      selections: { activities: [{ name: '<img src=x onerror=alert(1)>', price_usd: 10 }] },
    })
    expect(html).not.toContain('<script>alert(1)</script>')
    expect(html).not.toContain('<img src=x')
    expect(html).toContain('&lt;img src=x onerror=alert(1)&gt;')
  })

  it('only links to http(s) booking pages', () => {
    const html = build()
    expect(html).toContain('href="https://example.com/hotel"')
    expect(html).not.toContain('javascript:')
  })

  it('includes selected walking tours with safe links', () => {
    const html = build({ selections: { walking_tours: [
      { name: 'Old Town <b>Tour</b>', provider: 'GuruWalk', city: 'Tokyo', url: 'https://www.guruwalk.com/walks/1-tour' },
      { name: 'Sneaky Tour', provider: 'FreeTour.com', city: 'Tokyo', url: 'javascript:alert(1)' },
    ] } })
    expect(html).toContain('<h2>Free walking tours</h2>')
    expect(html).toContain('Old Town &lt;b&gt;Tour&lt;/b&gt;')
    expect(html).toContain('GuruWalk')
    expect(html).toContain('<a href="https://www.guruwalk.com/walks/1-tour">View tour</a>')
    expect(html).toContain('Sneaky Tour')
    expect(html).not.toContain('javascript:')
    expect(html.match(/View tour/g)).toHaveLength(1)
  })

  it('leaves out the walking tours section when none are selected', () => {
    expect(build()).not.toContain('Free walking tours')
  })

  it('locks the page down with a Content-Security-Policy', () => {
    const csp = /<meta http-equiv="Content-Security-Policy" content="([^"]+)">/.exec(build())?.[1]
    expect(csp).toContain("default-src 'none'")
    // Only the print button's own handler may run — nothing injected could
    expect(csp).toContain("script-src 'unsafe-hashes' 'sha256-")
    expect(csp).not.toContain("'unsafe-inline' 'self'")
  })

  it('pins exactly the print button\'s handler in the policy', () => {
    const html = build()
    const handler = /onclick="([^"]+)"/.exec(html)[1]
    const hash = createHash('sha256').update(handler).digest('base64')
    expect(html).toContain(`'sha256-${hash}'`)
  })

  it('includes the itinerary\'s own slot notes', () => {
    const html = build({ itinerary: { days: [{ day_number: 1, slots: [{ time_of_day: 'morning', activity: 'A', notes: 'Closed Mondays' }] }] } })
    expect(html).toContain('Closed Mondays')
  })

  it('has a print button that is hidden on paper', () => {
    const html = build()
    expect(html).toMatch(/<button[^>]*class="no-print"[^>]*>.*Print/)
    expect(html).toMatch(/@media print\s*{[^}]*\.no-print\s*{\s*display:\s*none/)
  })
})

describe('arranged itinerary in print', () => {
  const trip = {
    days: [
      { day_number: 1, city: 'Tokyo', slots: [
        { time_of_day: 'morning', activity: 'Tsukiji Outer Market' },
        { time_of_day: 'evening', activity: 'Shibuya Crossing' },
      ] },
      { day_number: 2, city: 'Tokyo', slots: [
        { time_of_day: 'morning', activity: 'Meiji Shrine' },
        { time_of_day: 'evening', activity: 'Izakaya crawl' },
      ] },
    ],
  }
  const html = (sel) => buildPlanPrintHtml({ planName: 'T', searchData, selections: sel, itinerary: trip })

  it('shows a moved activity under its new day with its edit and note', () => {
    const out = html({
      itinerary_layout: moveSlot(trip, null, '1-morning', 2, 'evening'),
      itinerary_edits: { '1-morning': { activity: 'Toyosu Market' } },
      itinerary_notes: { '1-morning': 'Go early' },
    })
    const day2 = out.slice(out.indexOf('Day 2'))
    expect(day2).toContain('Toyosu Market')
    expect(day2).toContain('Go early')
    expect(out.slice(0, out.indexOf('Day 2'))).not.toContain('Toyosu Market')
  })

  it('omits a removed activity', () => {
    expect(html({ itinerary_layout: removeSlot(trip, null, '1-morning') })).not.toContain('Tsukiji Outer Market')
  })
})
