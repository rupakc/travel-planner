// Plan export: a self-contained, print-friendly HTML page of the plan. The
// user prints it or saves it as a PDF from the browser's print dialog.
//
// Everything in a plan comes from AI agents or user input, so every value is
// HTML-escaped and only http(s) links are kept.

import { computePlanCostBreakdown } from './planHelpers'
import { planItineraryDays } from './planExport'
import { toRecentSearch, describeRecentSearch } from './recentSearches'

const ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }

export function escapeHtml(value) {
  return value == null ? '' : String(value).replace(/[&<>"']/g, (c) => ESCAPES[c])
}

/** The URL if it is a web link, else null (no javascript:, data:, etc.). */
export function safeUrl(value) {
  try {
    const url = new URL(value)
    return url.protocol === 'https:' || url.protocol === 'http:' ? url.href : null
  } catch {
    return null
  }
}

const usd = (n) => `$${Math.round(Number(n)).toLocaleString('en-US')}`
const esc = escapeHtml

const link = (url, label) => {
  const href = safeUrl(url)
  return href ? ` <a href="${esc(href)}">${esc(label)}</a>` : ''
}

const section = (title, body) => (body ? `<section><h2>${esc(title)}</h2>${body}</section>` : '')

const list = (items, render) => (items?.length ? `<ul>${items.map((it) => `<li>${render(it)}</li>`).join('')}</ul>` : '')

// "ANA NH9 · JFK → HND · 2027-04-01 11:55"
function legText(leg, fallback = {}) {
  const route = leg.origin && leg.destination
    ? `${leg.origin} → ${leg.destination}`
    : [fallback.from, fallback.to].filter(Boolean).map((p) => p.split(',')[0]).join(' → ')
  return [
    [leg.airline, leg.flight_number].filter(Boolean).join(' '),
    route,
    [leg.departure_date || fallback.date, leg.departure_time].filter(Boolean).join(' '),
  ].filter(Boolean).join(' · ')
}

function flightLine(f) {
  const out = legText(f.outbound || f, { from: f.leg_from, to: f.leg_to, date: f.leg_date })
  const ret = f.return ? `<br><span class="muted">Return:</span> ${esc(legText(f.return))}` : ''
  const price = Number(f.price_usd) > 0 ? ` <span class="amt">${usd(f.price_usd)}</span>` : ''
  return `${esc(out)}${price}${link(f.booking_url, 'Book')}${ret}`
}

function breakdownTable(selections, searchData) {
  const parts = computePlanCostBreakdown(selections, searchData)
  if (!parts.length) return ''
  const total = parts.reduce((t, p) => t + p.amount, 0)
  const rows = parts
    .map((p) => `<tr><td>${esc(p.label)}</td><td class="amt">${usd(p.amount)}</td><td class="pct">${Math.round((p.amount / total) * 100)}%</td></tr>`)
    .join('')
  const budget = searchData?.budget_usd > 0 ? `<p class="muted">Budget: ${usd(searchData.budget_usd)}</p>` : ''
  const transport = selections?.getting_around?.length ? '<p class="muted">Local transport isn\'t included — fares vary by trip.</p>' : ''
  return `<table class="costs">${rows}<tr class="total"><td>Total</td><td class="amt">${usd(total)}</td><td></td></tr></table>${budget}${transport}`
}

function itineraryHtml(days, selections) {
  if (!days.length) return ''
  return days.map((day) => {
    const slots = (day.slots || []).map((slot) => {
      const key = `${day.day_number}-${slot.time_of_day}`
      const edit = selections?.itinerary_edits?.[key] || {}
      const note = selections?.itinerary_notes?.[key]
      const activity = edit.activity ?? slot.activity
      const location = edit.location ?? slot.location
      const cost = edit.cost ?? slot.estimated_cost_usd
      const notes = [slot.notes, note].filter(Boolean).map((n) => `<div class="note">${esc(n)}</div>`).join('')
      return `<li><span class="when">${esc(slot.time_of_day)}</span> ${esc(activity)}${location ? ` <span class="muted">· ${esc(location)}</span>` : ''}${cost > 0 ? ` <span class="amt">${usd(cost)}</span>` : ''}${notes}</li>`
    }).join('')
    const heading = [`Day ${day.day_number}`, day.date, day.city, day.theme].filter(Boolean).map(esc).join(' · ')
    return `<div class="day"><h3>${heading}</h3><ul>${slots}</ul></div>`
  }).join('')
}

// The page shares the app's origin (it is a Blob URL), so as defence in depth
// nothing may run on it except the print button's handler, pinned by hash
// (sha256 of "window.print()").
const PRINT_HANDLER = 'window.print()'
const CSP = [
  "default-src 'none'",
  "style-src 'unsafe-inline'",
  'img-src https: data:',
  "script-src 'unsafe-hashes' 'sha256-MguIPR6qNR8D3B+eAlK+bIRTZe8t3wkOY4B/56Me9FU='",
  "base-uri 'none'",
  "form-action 'none'",
].join('; ')

const STYLES = `
  *{box-sizing:border-box}
  body{font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;color:#1f2937;background:#fff;margin:0 auto;max-width:780px;padding:32px 24px}
  h1{font-size:24px;margin:0 0 4px;color:#0f766e}
  h2{font-size:15px;margin:24px 0 8px;padding-bottom:4px;border-bottom:2px solid #ccfbf1;color:#115e59;text-transform:uppercase;letter-spacing:.04em}
  h3{font-size:14px;margin:12px 0 4px}
  ul{margin:0;padding-left:18px} li{margin:3px 0}
  a{color:#0d9488}
  .muted{color:#6b7280} .amt{font-weight:600;font-variant-numeric:tabular-nums}
  .when{display:inline-block;min-width:76px;text-transform:capitalize;color:#0f766e;font-weight:600}
  .note{margin:2px 0 4px 80px;font-style:italic;color:#4b5563}
  .day{break-inside:avoid}
  table.costs{border-collapse:collapse;min-width:320px} table.costs td{padding:3px 12px 3px 0}
  table.costs .pct{color:#6b7280} table.costs .total td{border-top:1px solid #d1d5db;font-weight:700}
  .toolbar{display:flex;justify-content:flex-end;margin-bottom:16px}
  .no-print{font:inherit;font-weight:600;color:#fff;background:#0d9488;border:0;border-radius:8px;padding:8px 14px;cursor:pointer}
  footer{margin-top:32px;font-size:12px;color:#9ca3af}
  @media print { .no-print { display: none } body{padding:0} a{color:inherit;text-decoration:none} }
`

/** A complete HTML document for printing / saving as PDF. */
export function buildPlanPrintHtml({ planName, searchData, selections, itinerary = null }) {
  const sel = selections || {}
  const name = planName || 'Trip plan'
  const trip = searchData?.origin && searchData?.destination && searchData?.departure_date
    ? describeRecentSearch(toRecentSearch(searchData))
    : null
  const summary = trip
    ? `<p class="muted">${esc(trip.route)} · ${esc(trip.dates)} · ${trip.travelers} traveler${trip.travelers === 1 ? '' : 's'}</p>`
    : ''

  const flights = [...(sel.flight ? [sel.flight] : []), ...(sel.flights || [])]
  const hotel = sel.hotel
    ? `<p><strong>${esc(sel.hotel.name)}</strong>${sel.hotel.location ? ` <span class="muted">· ${esc(sel.hotel.location)}</span>` : ''}${sel.hotel.price_per_night_usd > 0 ? ` · ${usd(sel.hotel.price_per_night_usd)}/night` : ''}${sel.hotel.total_price_usd > 0 ? ` · <span class="amt">${usd(sel.hotel.total_price_usd)} total</span>` : ''}${link(sel.hotel.booking_url, 'Book')}</p>`
    : ''

  const body = [
    section('Where the money goes', breakdownTable(sel, searchData)),
    section('Flights', list(flights, flightLine)),
    section('Hotel', hotel),
    section('Itinerary', itineraryHtml(planItineraryDays(sel, itinerary), sel)),
    section('Activities', list(sel.activities, (a) => `${esc(a.name)}${Number(a.price_usd) > 0 ? ` <span class="amt">${usd(a.price_usd)}</span>` : ''}${a.location ? ` <span class="muted">· ${esc(a.location)}</span>` : ''}${link(a.booking_url, 'Book')}`)),
    section('Places to see', list(sel.places_to_see, (p) => `${esc(p.name)}${p.neighbourhood ? ` <span class="muted">· ${esc(p.neighbourhood)}</span>` : ''}`)),
    section('Free walking tours', list(sel.walking_tours, (t) => `${esc(t.name)}${[t.provider, t.city].filter(Boolean).length ? ` <span class="muted">· ${esc([t.provider, t.city].filter(Boolean).join(' · '))}</span>` : ''}${link(t.url, 'View tour')}`)),
    section('Events', list(sel.events, (e) => `${esc(e.name)}${e.start_date ? ` <span class="muted">· ${esc(e.start_date)}${e.end_date && e.end_date !== e.start_date ? ` – ${esc(e.end_date)}` : ''}</span>` : ''}`)),
    section('SIM / eSIM', sel.sim ? `<p>${esc([sel.sim.provider, sel.sim.plan_name].filter(Boolean).join(' — '))}${Number(sel.sim.price_usd) > 0 ? ` <span class="amt">${usd(sel.sim.price_usd)}</span>` : ''}${link(sel.sim.url, 'Get plan')}</p>` : ''),
    section('Getting around', list(sel.getting_around, (t) => `${esc(t.name)}${t.price_info ? ` <span class="muted">· ${esc(t.price_info)}</span>` : ''}`)),
    section('Tips', list(sel.tips, (t) => `<strong>${esc(t.title)}</strong>${t.body ? ` — ${esc(t.body)}` : ''}`)),
  ].join('')

  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="${CSP}">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${esc(name)}</title>
<style>${STYLES}</style>
</head>
<body>
<div class="toolbar"><button type="button" class="no-print" onclick="${PRINT_HANDLER}">Print / Save as PDF</button></div>
<h1>${esc(name)}</h1>
${summary}
${body}
<footer>Planned with Voyager. Prices and availability are estimates — confirm before booking.</footer>
</body>
</html>
`
}
