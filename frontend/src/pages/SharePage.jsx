import { useState, useEffect, useCallback, useRef } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  Loader2, Download, Plane, Hotel, MapPin, Calendar, Users, Smartphone, Bus,
  PartyPopper, Star, Clock, DollarSign, Lightbulb, Wifi, Footprints,
} from 'lucide-react'
import { computePlanCost } from '../utils/planHelpers'
import { safeUrl } from '../utils/planPrint'
import { arrangeItinerary, slotKey } from '../utils/itineraryLayout'
import { scheduleDays, timeRange } from '../utils/schedule'
import FromLinkChip, { InspiredBy } from '../components/FromLinkChip'
import AttributionFooter from '../components/ui/AttributionFooter'
import i18n from '../i18n'
import { fmtDate, fmtNumber } from '../i18n/format'
import { SCRIPT_FONTS } from '../i18n/languages'
import { wrapCanvasText } from '../utils/wrapCanvasText'

// Module-level helpers (and the canvas card) have no hook: look the copy up at
// call time. SharePage itself calls useTranslation so it re-renders on a
// language switch.
const tt = (key, opts) => i18n.t(`misc:${key}`, opts)
// Non-numeric amounts render nothing rather than `$NaN`
const usd = (n) => (n != null && n !== '' && Number.isFinite(Number(n)) ? `$${fmtNumber(Number(n))}` : '')
// ISO date strings from the plan, in the reader's locale; raw text if unparsable
const dateText = (d) => MONTH_ONLY.test(String(d)) ? monthText(d) : fmtDate(`${d}T00:00:00`, { month: 'short', day: 'numeric', year: 'numeric' }) || String(d)

const FONT_TIMEOUT_MS = 1500
const FONT_WEIGHTS = [400, 600, 700]

// Starts (or awaits) the script font the canvas will draw with. Calling it
// early (on mount / language change) means the await at click time is instant,
// which keeps the download inside the browser's user-activation window.
function loadCardFonts(lang, sample) {
  const family = SCRIPT_FONTS[lang]
  if (!family || typeof document === 'undefined' || !document.fonts?.load) return Promise.resolve()
  return Promise.all(FONT_WEIGHTS.map((w) => document.fonts.load(`${w} 30px "${family}"`, sample)))
}

const fontSample = (lang, plan) => {
  let bundle = ''
  try { bundle = JSON.stringify(i18n.getResourceBundle(lang, 'misc') || {}) } catch { /* none */ }
  return `${bundle}${plan?.name || ''}${plan?.search_data?.destination || ''}`.slice(0, 2000)
}
const fontStack = (lang) => (SCRIPT_FONTS[lang] ? `"${SCRIPT_FONTS[lang]}", system-ui, sans-serif` : 'system-ui, sans-serif')
const stopsText = (n) => (n === 0 ? tt('share.nonstop') : tt('share.stops', { count: n }))

// Public, read-only trip card — reachable without login via /share/:token

const GRADIENTS = [
  ['#0d9488', '#0284c7'],
  ['#7c3aed', '#db2777'],
  ['#ea580c', '#ca8a04'],
  ['#059669', '#0891b2'],
]

function pickGradient(name = '') {
  let h = 0
  for (const ch of name) h = (h * 31 + ch.charCodeAt(0)) % 997
  return GRADIENTS[h % GRADIENTS.length]
}

const MONTH_ONLY = /^\d{4}-\d{2}$/
// 'YYYY-MM' (month-only share) -> "Mar 2026"; anything unparsable is shown as text
const monthText = (m) => fmtDate(`${m}-01T00:00:00`, { month: 'short', year: 'numeric' }) || String(m)

function tripDates(sd) {
  if (!sd?.departure_date) return null
  if (MONTH_ONLY.test(String(sd.departure_date))) return monthText(sd.departure_date)
  const opts = { month: 'short', day: 'numeric', year: 'numeric' }
  const dep = fmtDate(`${sd.departure_date}T00:00:00`, opts)
  if (!sd.return_date) return dep
  const ret = fmtDate(`${sd.return_date}T00:00:00`, opts)
  return `${dep} → ${ret}`
}

function destinationLabel(sd) {
  if (sd?.destinations?.length > 1) return sd.destinations.join(' → ')
  return sd?.destination || tt('share.defaultDestination')
}

const city = (c) => String(c || '').split(',')[0].trim()

function fmtDuration(mins) {
  if (!mins) return null
  return tt('share.duration', { h: Math.floor(mins / 60), m: mins % 60 })
}

// One flight leg's detail line (works for outbound, return and multi-city legs)
function FlightRow({ tag, leg, price }) {
  if (!leg) return null
  return (
    <div className="flex items-start gap-2 text-sm">
      <span className="shrink-0 px-1.5 py-0.5 rounded bg-sky-100 text-sky-700 text-xs font-semibold mt-0.5">{tag}</span>
      <div className="min-w-0 flex-1">
        <p className="text-gray-800 font-medium">
          {leg.airline || tt('share.flight')}{leg.flight_number ? ` ${leg.flight_number}` : ''}
          {price != null && <span className="text-sky-700 font-bold"> · {usd(price)}</span>}
        </p>
        <p className="text-xs text-gray-500">
          {leg.origin} → {leg.destination}
          {leg.departure_date ? ` · ${dateText(leg.departure_date)}` : ''}
          {leg.departure_time ? ` · ${leg.departure_time}–${leg.arrival_time || '?'}` : ''}
          {fmtDuration(leg.duration_minutes) ? ` · ${fmtDuration(leg.duration_minutes)}` : ''}
          {leg.stops != null ? ` · ${stopsText(leg.stops)}` : ''}
        </p>
      </div>
    </div>
  )
}

function DetailCard({ title, icon: Icon, accent, children }) {
  return (
    <div className="bg-white rounded-2xl shadow-lg p-5">
      <h2 className={`text-sm font-bold mb-3 flex items-center gap-1.5 ${accent}`}>
        <Icon size={14} /> {title}
      </h2>
      {children}
    </div>
  )
}

// Draws the FULL trip page (poster + every detail section) onto a canvas
// and triggers a PNG download — no extra deps. Two passes: measure, then draw.
async function downloadCard(plan) {
  const sd = plan.search_data || {}
  const sel = plan.selections || {}
  const [c1, c2] = pickGradient(plan.name)
  const W = 1080
  const M = 80            // left/right margin
  const maxW = W - M * 2

  // ── Build the line plan ────────────────────────────────────────────
  const lines = []
  const add = (text, { size = 30, weight = 400, color = '#ffffff', gap = 14, indent = 0 } = {}) =>
    lines.push({ text, size, weight, color, indent, gap })
  const space = (gap) => lines.push({ text: '', size: 0, gap })
  const section = (title) => { space(34); add(title, { size: 40, weight: 700, gap: 20 }) }
  const dim = 'rgba(255,255,255,0.78)'
  const faint = 'rgba(255,255,255,0.62)'

  add(tt('share.posterTag').toUpperCase(), { size: 34, weight: 600, color: dim, gap: 26 })
  add(destinationLabel(sd), { size: 68, weight: 700, gap: 18 })
  const dates = tripDates(sd)
  if (dates) add(dates, { size: 38, color: dim, gap: 8 })
  if (sd.origin) add(`${tt('share.fromOrigin', { origin: sd.origin })} · ${tt('share.travelers', { count: sd.num_travelers || 1 })}`, { size: 34, color: dim, gap: 8 })
  const totalCost = computePlanCost(sel, sd)
  if (totalCost > 0) add(tt('share.plannedSpend', { amount: usd(Math.round(totalCost)) }), { size: 34, weight: 600, gap: 8 })
  if ((sd.interests || []).length) add(`✨ ${sd.interests.slice(0, 5).join(' · ')}`, { size: 30, color: faint, gap: 8 })

  const legFlights = sel.flights || []
  if (legFlights.length || sel.flight) {
    section(`✈️ ${tt('share.flightsTitle')}`)
    const legLine = (tag, leg, price) => {
      if (!leg) return
      add(`${tag}: ${leg.airline || tt('share.flight')}${leg.flight_number ? ' ' + leg.flight_number : ''}${price != null ? ` — ${usd(price)}` : ''}`, { size: 32, weight: 600, gap: 4 })
      const bits = [
        `${leg.origin || ''} → ${leg.destination || ''}`,
        leg.departure_date ? dateText(leg.departure_date) : null,
        leg.departure_time ? `${leg.departure_time}–${leg.arrival_time || '?'}` : null,
        fmtDuration(leg.duration_minutes),
        leg.stops != null ? stopsText(leg.stops) : null,
      ].filter(Boolean).join(' · ')
      add(bits, { size: 27, color: dim, indent: 30, gap: 14 })
    }
    if (legFlights.length) {
      legFlights.forEach((f, i) => legLine(tt('share.leg', { n: (f.leg_index ?? i) + 1 }), {
        ...(f.outbound || {}),
        origin: city(f.leg_from) || f.outbound?.origin,
        destination: city(f.leg_to) || f.outbound?.destination,
        departure_date: f.leg_date,
      }, f.price_usd))
      const t = legFlights.reduce((a, f) => a + (Number(f.price_usd) || 0), 0)
      if (t) add(tt('share.totalFlights', { amount: usd(t) }), { size: 28, weight: 600, gap: 6 })
    } else if (sel.flight.outbound) {
      legLine(tt('share.depart'), sel.flight.outbound, sel.flight.price_usd)
      if (sel.flight.return) legLine(tt('share.return'), sel.flight.return)
    } else {
      legLine(tt('share.flight'), sel.flight, sel.flight.price_usd)
    }
  }

  if (sel.hotel) {
    section(`🏨 ${tt('share.hotelTitle')}`)
    add(`${sel.hotel.name}${sel.hotel.star_rating ? ` · ${'★'.repeat(Math.round(sel.hotel.star_rating))}` : ''}`, { size: 32, weight: 600, gap: 4 })
    const bits = [sel.hotel.location, sel.hotel.price_per_night_usd ? tt('share.perNight', { amount: usd(sel.hotel.price_per_night_usd) }) : null, sel.hotel.total_price_usd ? tt('share.total', { amount: usd(sel.hotel.total_price_usd) }) : null].filter(Boolean).join(' · ')
    if (bits) add(bits, { size: 27, color: dim, indent: 30, gap: 6 })
  }

  const arranged = sel.itinerary?.days?.length ? arrangeItinerary(sel.itinerary, sel.itinerary_layout, sel.itinerary_edits) : null
  const itinDays = arranged ? scheduleDays(arranged.days, sel.itinerary_edits) : []
  if (itinDays.length) {
    section(`📅 ${tt('share.canvasItinerary', { count: itinDays.length })}`)
    for (const day of itinDays) {
      add(`${tt('share.dayN', { n: day.day_number })}${day.date ? ` · ${dateText(day.date)}` : ''}${day.city ? ` · ${city(day.city)}` : ''}${day.theme ? ` — ${day.theme}` : ''}`, { size: 30, weight: 700, gap: 6 })
      for (const slot of day.slots || []) {
        const key = slot.key ?? slotKey(day.day_number, slot.time_of_day)
        const edit = sel.itinerary_edits?.[key] || {}
        const note = sel.itinerary_notes?.[key]
        const range = timeRange(slot)
        add(`${slot.time_of_day}${range ? ` ${range}` : ''}: ${edit.activity || slot.activity}${note ? ` (📝 ${note})` : ''}`, { size: 27, color: dim, indent: 30, gap: 4 })
      }
      space(10)
    }
    if (arranged?.total_estimated_cost_usd > 0) add(tt('share.estCost', { amount: usd(arranged.total_estimated_cost_usd) }), { size: 28, weight: 600, gap: 6 })
  }

  const listSection = (title, items, fmt) => {
    if (!items?.length) return
    section(title)
    for (const item of items) add(`• ${fmt(item)}`, { size: 28, color: dim, gap: 8 })
  }
  listSection(`🎯 ${tt('share.activitiesTitle', { n: (sel.activities || []).length })}`, sel.activities, a =>
    `${a.name}${a.city ? ` — ${city(a.city)}` : ''}${a.price_usd != null ? ` (${usd(a.price_usd)})` : ''}`)
  listSection(`🎉 ${tt('share.eventsTitle', { n: (sel.events || []).length })}`, sel.events, e =>
    `${e.name}${e.city ? ` — ${city(e.city)}` : ''}${e.start_date ? ` (${dateText(e.start_date)})` : ''}`)
  listSection(`🚶 ${tt('share.walkingToursTitle', { n: (sel.walking_tours || []).length })}`, sel.walking_tours, wt =>
    `${wt.name}${wt.city ? ` — ${city(wt.city)}` : ''}${wt.provider ? ` (${wt.provider})` : ''}`)
  if (sel.sim) listSection(`📶 ${tt('share.simTitle')}`, [sel.sim], s2 =>
    `${s2.provider} ${s2.plan_name || ''}${s2.price_usd != null ? ` (${usd(s2.price_usd)})` : ''}`)
  listSection(`🚇 ${tt('share.gettingAroundTitle', { n: (sel.getting_around || []).length })}`, sel.getting_around, o =>
    `${o.name}${o.city ? ` — ${city(o.city)}` : ''}`)
  listSection(`💡 ${tt('share.tipsTitle', { n: (sel.tips || []).length })}`, sel.tips, tip => tip.title)

  space(40)
  add(plan.name || tt('share.defaultPlanName'), { size: 30, color: faint, gap: 0 })

  // ── Measure (with wrapping), then draw ─────────────────────────────
  // The Noto family for this language's script is loaded lazily by the i18n
  // framework; wait (briefly) for it so measuring and drawing use the same font.
  const stack = fontStack(i18n.resolvedLanguage || i18n.language)
  if (stack.startsWith('"')) {
    const sample = lines.map((l) => l.text).join('').slice(0, 2000)
    let timer
    const timeout = new Promise((resolve) => { timer = setTimeout(resolve, FONT_TIMEOUT_MS) })
    try {
      await Promise.race([loadCardFonts(i18n.resolvedLanguage || i18n.language, sample), timeout])
    } catch { /* fall back to the system font */ }
    clearTimeout(timer)
  }

  const measurer = document.createElement('canvas').getContext('2d')
  const wrapped = []
  for (const ln of lines) {
    if (!ln.text) { wrapped.push(ln); continue }
    measurer.font = `${ln.weight} ${ln.size}px ${stack}`
    const parts = wrapCanvasText(String(ln.text), maxW - ln.indent, (txt) => measurer.measureText(txt).width)
    parts.forEach((text, i) => wrapped.push({ ...ln, text, gap: i < parts.length - 1 ? 6 : ln.gap }))
  }

  const TOP = 110, BOTTOM = 90
  const H = Math.ceil(TOP + wrapped.reduce((h, ln) => h + ln.size * 1.18 + ln.gap, 0) + BOTTOM)
  const canvas = document.createElement('canvas')
  canvas.width = W
  canvas.height = H
  const ctx = canvas.getContext('2d')

  const grad = ctx.createLinearGradient(0, 0, W, H)
  grad.addColorStop(0, c1)
  grad.addColorStop(1, c2)
  ctx.fillStyle = grad
  ctx.fillRect(0, 0, W, H)
  ctx.fillStyle = 'rgba(255,255,255,0.10)'
  ctx.beginPath(); ctx.arc(W - 110, 150, 220, 0, Math.PI * 2); ctx.fill()
  ctx.beginPath(); ctx.arc(70, H - 170, 260, 0, Math.PI * 2); ctx.fill()

  let y = TOP
  for (const ln of wrapped) {
    y += ln.size * 1.18
    if (ln.text) {
      ctx.font = `${ln.weight} ${ln.size}px ${stack}`
      ctx.fillStyle = ln.color
      ctx.fillText(ln.text, M + ln.indent, y)
    }
    y += ln.gap
  }

  const a = document.createElement('a')
  a.download = `${(plan.name || 'trip-card').replace(/[^a-z0-9]+/gi, '-').toLowerCase()}.png`
  const dataUrl = canvas.toDataURL('image/png')
  a.href = dataUrl
  try {
    a.click()
  } catch {
    // The download click can't run here: open the image so it can be saved
    // from the new tab (a null window means popups are blocked: report it).
    if (!window.open(dataUrl, '_blank')) throw new Error('download blocked')
  }
}

const SHARE_KINDS = ['plan', 'recap', 'savings', 'quiz', 'status']
const CARD_KINDS = ['recap', 'savings', 'quiz', 'status']
const CARD_TAG = { recap: 'page.recapTag', savings: 'page.savingsTag', quiz: 'page.quizTag', status: 'page.statusTag' }

// Recap and savings shares: a card (headline, stats, destination, period), no plan body.
function CardView({ plan, ts }) {
  const card = plan.card || {}
  const [c1, c2] = pickGradient(plan.name || card.headline)
  const stats = (Array.isArray(card.stats) ? card.stats : []).filter((s) => s && Number.isFinite(Number(s.count)))
  const period = card.period ? (MONTH_ONLY.test(String(card.period)) ? monthText(card.period) : String(card.period)) : ''
  return (
    <div data-tid="share.card" className="rounded-3xl shadow-2xl overflow-hidden text-white relative" style={{ background: `linear-gradient(135deg, ${c1}, ${c2})` }}>
      <div className="relative p-8 space-y-5">
        <p className="text-sm font-semibold tracking-widest uppercase text-white/80">{ts(CARD_TAG[plan.kind] || 'page.recapTag')}</p>
        <h1 className="text-3xl font-bold leading-tight">{card.headline}</h1>
        {(card.destination || period) && (
          <p className="text-white/90 text-sm">{[card.destination, period].filter(Boolean).join(' · ')}</p>
        )}
        {stats.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {stats.map((s) => (
              <span key={s.key} className="px-3 py-1.5 rounded-full bg-white/20 text-sm font-medium">
                {fmtNumber(Number(s.count))} {ts(`page.stat.${s.key}`, { defaultValue: String(s.key || '').replace(/_/g, ' ') })}
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

export default function SharePage({ download = downloadCard }) {
  const { t, i18n: i18nHook } = useTranslation('misc')
  const { t: ts } = useTranslation('share')
  const { token } = useParams()
  const [plan, setPlan] = useState(null)
  const [status, setStatus] = useState('loading')
  const [downloading, setDownloading] = useState(false)
  const [downloadFailed, setDownloadFailed] = useState(false)
  const busy = useRef(false)

  useEffect(() => {
    fetch(`/api/share/${encodeURIComponent(token)}`)
      .then(r => (r.ok ? r.json() : Promise.reject()))
      .then(data => { setPlan(data); setStatus('done') })
      .catch(() => setStatus('error'))
  }, [token])

  // Public pages stay out of search engines (the API also sends X-Robots-Tag)
  useEffect(() => {
    const m = document.createElement('meta')
    m.name = 'robots'
    m.content = 'noindex'
    document.head.appendChild(m)
    return () => m.remove()
  }, [])

  useEffect(() => {
    if (status !== 'done' || !plan) return
    import('../telemetry/client').then((m) => m.emit('share_view', { kind: SHARE_KINDS.includes(plan.kind) ? plan.kind : 'plan' })).catch(() => {})
  }, [status, plan])

  // Warm the script font as soon as the plan is here (and when the language changes)
  const lang = i18nHook.resolvedLanguage || i18nHook.language
  useEffect(() => {
    if (plan) loadCardFonts(lang, fontSample(lang, plan)).catch(() => {})
  }, [plan, lang])

  const handleDownload = useCallback(async () => {
    if (!plan || busy.current) return
    busy.current = true
    setDownloading(true)
    setDownloadFailed(false)
    try {
      await download(plan)
    } catch {
      setDownloadFailed(true)
    } finally {
      busy.current = false
      setDownloading(false)
    }
  }, [plan, download])

  if (status === 'loading') {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-sky-100 via-teal-50 to-emerald-100">
        <Loader2 size={28} className="animate-spin text-teal-500" />
      </div>
    )
  }
  if (status === 'error') {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center gap-3 bg-gradient-to-br from-sky-100 via-teal-50 to-emerald-100 px-4 text-center">
        <p className="text-4xl">🗺️</p>
        <h1 className="text-xl font-bold text-slate-800">{t('share.unavailableTitle')}</h1>
        <p className="text-sm text-slate-500">{t('share.unavailableBody')}</p>
        <Link to="/" data-tid="share.plan-own-error" className="mt-2 px-5 py-2.5 bg-teal-700 text-white text-sm font-semibold rounded-xl hover:bg-teal-800 transition-colors">{t('share.planOwn')}</Link>
        <AttributionFooter />
      </div>
    )
  }

  const byline = typeof plan.owner_name === 'string' && plan.owner_name.trim()
    ? <p data-tid="share.byline" className="text-center text-sm text-slate-600">{ts('page.byline', { name: plan.owner_name })}</p>
    : null

  if (CARD_KINDS.includes(plan.kind) && plan.card) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-sky-100 via-teal-50 to-emerald-100 py-10 px-4">
        <div className="max-w-lg mx-auto space-y-6">
          <CardView plan={plan} ts={ts} />
          {byline}
          <Link to="/" data-tid="share.plan-own" className="flex items-center justify-center gap-2 px-5 py-3 bg-teal-700 text-white font-semibold rounded-xl hover:bg-teal-800 transition-colors shadow-md text-sm">
            {ts('page.cta')}
          </Link>
        </div>
        <AttributionFooter />
      </div>
    )
  }

  const sd = plan.search_data || {}
  const sel = plan.selections || {}
  const [c1, c2] = pickGradient(plan.name)
  const travelers = sd.num_travelers || 1
  const totalCost = computePlanCost(sel, sd)
  const arranged = sel.itinerary?.days?.length ? arrangeItinerary(sel.itinerary, sel.itinerary_layout, sel.itinerary_edits) : null
  const itinDays = arranged ? scheduleDays(arranged.days, sel.itinerary_edits) : []
  const legFlights = sel.flights || []

  // Fallback itinerary from individually-selected slots when no full snapshot
  const slotsByDay = {}
  if (!itinDays.length) {
    for (const slot of sel.itinerary_slots || []) {
      (slotsByDay[slot.day_number] = slotsByDay[slot.day_number] || []).push(slot)
    }
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-sky-100 via-teal-50 to-emerald-100 py-10 px-4">
      <div className="max-w-lg mx-auto space-y-6">
        {/* Poster card */}
        <div className="rounded-3xl shadow-2xl overflow-hidden text-white relative" style={{ background: `linear-gradient(135deg, ${c1}, ${c2})`, '--c-white': '255 255 255' }}>
          <div className="absolute -top-16 -right-16 w-56 h-56 rounded-full bg-white/10" />
          <div className="absolute -bottom-20 -left-16 w-64 h-64 rounded-full bg-white/10" />
          <div className="relative p-8 space-y-5">
            <p className="text-sm font-semibold tracking-widest uppercase text-white/80">{t('share.posterTag')}</p>
            <div>
              <h1 className="text-3xl font-bold leading-tight">{destinationLabel(sd)}</h1>
              {sd.origin && <p className="text-white/80 text-sm mt-1">{t('share.fromOrigin', { origin: sd.origin })}</p>}
              {sd.import_source && <InspiredBy source={sd.import_source} className="mt-2 text-sm text-white/90 [&_a]:text-white" />}
            </div>
            <div className="flex flex-wrap gap-x-4 gap-y-1.5 text-sm text-white/90">
              {tripDates(sd) && <span className="flex items-center gap-1.5"><Calendar size={13} />{tripDates(sd)}</span>}
              <span className="flex items-center gap-1.5"><Users size={13} />{t('share.travelers', { count: travelers })}</span>
              {totalCost > 0 && <span className="flex items-center gap-1.5"><DollarSign size={13} />{t('share.planned', { amount: usd(Math.round(totalCost)) })}</span>}
            </div>
            {(sd.interests || []).length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {sd.interests.map(i => (
                  <span key={i} className="px-2.5 py-1 rounded-full bg-white/20 text-xs font-medium">{i}</span>
                ))}
              </div>
            )}
            <div className="space-y-2 pt-2 border-t border-white/20 text-sm">
              {legFlights.length > 0 && <p className="flex items-center gap-2"><Plane size={14} className="shrink-0" />{t('share.flightLegs', { count: legFlights.length })}</p>}
              {!legFlights.length && sel.flight?.outbound?.airline && <p className="flex items-center gap-2"><Plane size={14} className="shrink-0" />{sel.flight.outbound.airline}{sel.flight.price_usd ? ` — ${usd(sel.flight.price_usd)}` : ''}</p>}
              {sel.hotel?.name && <p className="flex items-center gap-2"><Hotel size={14} className="shrink-0" />{sel.hotel.name}</p>}
              {(sel.activities || []).length > 0 && <p className="flex items-center gap-2"><MapPin size={14} className="shrink-0" />{t('share.activitiesPlanned', { count: sel.activities.length })}</p>}
              {itinDays.length > 0 && <p className="flex items-center gap-2"><Calendar size={14} className="shrink-0" />{t('share.itineraryBelow', { count: itinDays.length })}</p>}
              {sel.sim?.provider && <p className="flex items-center gap-2"><Smartphone size={14} className="shrink-0" />{sel.sim.provider}</p>}
              {(sel.getting_around || []).length > 0 && <p className="flex items-center gap-2"><Bus size={14} className="shrink-0" />{t('share.transportPicks', { count: sel.getting_around.length })}</p>}
              {(sel.walking_tours || []).length > 0 && <p className="flex items-center gap-2"><Footprints size={14} className="shrink-0" />{t('share.walkingTours', { count: sel.walking_tours.length })}</p>}
              {(sel.events || []).length > 0 && <p className="flex items-center gap-2"><PartyPopper size={14} className="shrink-0" />{t('share.events', { count: sel.events.length })}</p>}
            </div>
            <p className="text-white/70 text-xs pt-2">{plan.name}</p>
          </div>
        </div>

        {byline}

        {/* Flights */}
        {(legFlights.length > 0 || sel.flight) && (
          <DetailCard title={t('share.flightsTitle')} icon={Plane} accent="text-sky-700">
            <div className="space-y-3">
              {legFlights.length > 0
                ? legFlights.map((f, i) => (
                    <FlightRow key={i}
                      tag={t('share.leg', { n: (f.leg_index ?? i) + 1 })}
                      leg={{
                        ...(f.outbound || {}),
                        origin: city(f.leg_from) || f.outbound?.origin,
                        destination: city(f.leg_to) || f.outbound?.destination,
                        departure_date: f.leg_date || f.outbound?.departure_date,
                      }}
                      price={f.price_usd} />
                  ))
                : (
                  <>
                    {sel.flight.outbound
                      ? (
                        <>
                          <FlightRow tag={t('share.depart')} leg={sel.flight.outbound} price={sel.flight.price_usd} />
                          {sel.flight.return && <FlightRow tag={t('share.return')} leg={sel.flight.return} />}
                        </>
                      )
                      : <FlightRow tag={t('share.flight')} leg={sel.flight} price={sel.flight.price_usd} />}
                  </>
                )}
              {legFlights.length > 1 && (
                <p className="text-xs font-semibold text-sky-700 pt-1 border-t border-gray-100">
                  {t('share.totalFlights', { amount: usd(legFlights.reduce((sum, f) => sum + (Number(f.price_usd) || 0), 0)) })}
                </p>
              )}
            </div>
          </DetailCard>
        )}

        {/* Hotel */}
        {sel.hotel && (
          <DetailCard title={t('share.hotelTitle')} icon={Hotel} accent="text-purple-700">
            <p className="text-sm font-semibold text-gray-900">{sel.hotel.name}</p>
            <div className="flex items-center gap-2 mt-1">
              {sel.hotel.star_rating > 0 && (
                <span className="flex">{[...Array(Math.round(sel.hotel.star_rating))].map((_, j) => <Star key={j} size={11} className="text-yellow-400 fill-yellow-400" />)}</span>
              )}
              {sel.hotel.review_score && <span className="text-xs text-gray-500">{sel.hotel.review_score}/10</span>}
              {sel.hotel.city && <span className="text-xs text-indigo-600 font-medium">{city(sel.hotel.city)}</span>}
            </div>
            <p className="text-xs text-gray-500 mt-1">
              {sel.hotel.location}
              {sel.hotel.price_per_night_usd ? ` · ${t('share.perNight', { amount: usd(sel.hotel.price_per_night_usd) })}` : ''}
              {sel.hotel.total_price_usd ? ` · ${t('share.total', { amount: usd(sel.hotel.total_price_usd) })}` : ''}
            </p>
            {(sel.hotel.amenities || []).length > 0 && (
              <div className="flex flex-wrap gap-1 mt-2">
                {sel.hotel.amenities.slice(0, 6).map(a => <span key={a} className="px-1.5 py-0.5 bg-gray-100 text-gray-600 rounded text-xs">{a}</span>)}
              </div>
            )}
          </DetailCard>
        )}

        {/* Full itinerary */}
        {itinDays.length > 0 && (
          <DetailCard title={t('share.itineraryTitle', { count: itinDays.length })} icon={Calendar} accent="text-teal-700">
            <div className="space-y-4">
              {itinDays.map((day, i) => (
                <div key={i}>
                  <p className="text-xs font-bold text-teal-700 uppercase tracking-wide">
                    {t('share.dayN', { n: day.day_number })}{day.date ? ` · ${dateText(day.date)}` : ''}{day.city ? ` · ${city(day.city)}` : ''}
                  </p>
                  {day.theme && <p className="text-xs text-gray-400 italic">{day.theme}</p>}
                  <ul className="mt-1.5 space-y-1">
                    {(day.slots || []).map((slot, j) => {
                      const key = slot.key ?? slotKey(day.day_number, slot.time_of_day)
                      const edit = sel.itinerary_edits?.[key] || {}
                      const note = sel.itinerary_notes?.[key]
                      return (
                        <li key={j} className="flex items-start gap-2 text-sm text-gray-700">
                          <span className="shrink-0 w-20 text-xs text-gray-400 mt-0.5">
                            <span className="capitalize">{slot.time_of_day}</span>
                            {timeRange(slot) && <span className="block text-[11px] tabular-nums">{timeRange(slot)}</span>}
                          </span>
                          <span className="min-w-0">
                            {edit.activity || slot.activity}
                            {(edit.location ?? slot.location) && <span className="text-gray-400 text-xs"> — {edit.location ?? slot.location}</span>}
                            {slot.from_link && <FromLinkChip quote={slot.link_quote} note={slot.link_note} className="ml-1.5 align-middle" />}
                            {note && <span className="block text-xs text-teal-600 italic">📝 {note}</span>}
                          </span>
                        </li>
                      )
                    })}
                  </ul>
                  {(day.link_extras || []).length > 0 && (
                    <p className="mt-1 text-xs text-amber-800">{t('share.alsoFromLink', { names: day.link_extras.map((x) => x.name).join(', ') })}</p>
                  )}
                </div>
              ))}
              {arranged?.total_estimated_cost_usd > 0 && (
                <p className="text-xs font-semibold text-teal-700 pt-2 border-t border-gray-100">
                  {t('share.estCost', { amount: usd(arranged.total_estimated_cost_usd) })}
                </p>
              )}
            </div>
          </DetailCard>
        )}

        {/* Itinerary picks fallback (no full snapshot saved) */}
        {!itinDays.length && Object.keys(slotsByDay).length > 0 && (
          <DetailCard title={t('share.itineraryPicks')} icon={Calendar} accent="text-teal-700">
            <div className="space-y-3">
              {Object.keys(slotsByDay).sort((a, b) => a - b).map(dayNum => (
                <div key={dayNum}>
                  <p className="text-xs font-bold text-teal-700 uppercase tracking-wide">{t('share.dayN', { n: dayNum })}</p>
                  <ul className="mt-1 space-y-1">
                    {slotsByDay[dayNum].map((slot, j) => (
                      <li key={j} className="flex items-start gap-2 text-sm text-gray-700">
                        <span className="shrink-0 w-20 text-xs text-gray-400 capitalize mt-0.5">{slot.time_of_day}</span>
                        <span>{timeRange(slot) && <span className="text-teal-600 text-xs mr-1">{timeRange(slot)}</span>}{slot.activity}{slot.location && <span className="text-gray-400 text-xs"> — {slot.location}</span>}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </DetailCard>
        )}

        {/* Activities */}
        {(sel.activities || []).length > 0 && (
          <DetailCard title={t('share.activitiesTitle', { n: sel.activities.length })} icon={MapPin} accent="text-green-700">
            <ul className="space-y-2.5">
              {sel.activities.map((a, i) => (
                <li key={i} className="text-sm">
                  <p className="text-gray-800 font-medium">
                    {a.name}
                    {a.city && <span className="ml-1.5 text-xs text-indigo-600 font-semibold">{city(a.city)}</span>}
                  </p>
                  <p className="text-xs text-gray-500 flex flex-wrap items-center gap-x-2">
                    {a.category && <span className="capitalize">{a.category}</span>}
                    {a.duration_hours && <span className="flex items-center gap-0.5"><Clock size={9} />{t('share.hours', { n: a.duration_hours })}</span>}
                    {a.price_usd != null && <span>{usd(a.price_usd)}</span>}
                    {a.location && <span>{a.location}</span>}
                  </p>
                </li>
              ))}
            </ul>
          </DetailCard>
        )}

        {/* Events */}
        {(sel.events || []).length > 0 && (
          <DetailCard title={t('share.eventsTitle', { n: sel.events.length })} icon={PartyPopper} accent="text-fuchsia-700">
            <ul className="space-y-2.5">
              {sel.events.map((ev, i) => (
                <li key={i} className="text-sm">
                  <p className="text-gray-800 font-medium">
                    {ev.name}
                    {ev.city && <span className="ml-1.5 text-xs text-indigo-600 font-semibold">{city(ev.city)}</span>}
                  </p>
                  <p className="text-xs text-gray-500 flex flex-wrap items-center gap-x-2">
                    {ev.category && <span className="capitalize">{ev.category}</span>}
                    {ev.start_date && <span>{dateText(ev.start_date)}{ev.end_date && ev.end_date !== ev.start_date ? ` – ${dateText(ev.end_date)}` : ''}</span>}
                    {ev.price && <span>{ev.price}</span>}
                    {ev.location && <span>{ev.location}</span>}
                  </p>
                </li>
              ))}
            </ul>
          </DetailCard>
        )}

        {/* Free walking tours */}
        {(sel.walking_tours || []).length > 0 && (
          <DetailCard title={t('share.walkingToursTitle', { n: sel.walking_tours.length })} icon={Footprints} accent="text-green-700">
            <ul className="space-y-2.5">
              {sel.walking_tours.map((tour, i) => {
                const href = safeUrl(tour.url)
                return (
                  <li key={tour.url || i} className="text-sm">
                    <p className="text-gray-800 font-medium">
                      {href ? (
                        <a data-tid="share.item-link" href={href} target="_blank" rel="noopener noreferrer" className="hover:underline">{tour.name}</a>
                      ) : tour.name}
                      {tour.city && <span className="ml-1.5 text-xs text-indigo-600 font-semibold">{city(tour.city)}</span>}
                    </p>
                    {tour.provider && <p className="text-xs text-gray-500">{tour.provider}</p>}
                  </li>
                )
              })}
            </ul>
          </DetailCard>
        )}

        {/* SIM */}
        {sel.sim && (
          <DetailCard title={t('share.simTitle')} icon={Smartphone} accent="text-pink-700">
            <p className="text-sm font-medium text-gray-800">{sel.sim.provider} — {sel.sim.plan_name}</p>
            <p className="text-xs text-gray-500 mt-0.5 flex flex-wrap items-center gap-x-2">
              {sel.sim.price_usd != null && <span className="font-semibold text-pink-700">{usd(sel.sim.price_usd)}</span>}
              {sel.sim.data_gb ? <span>{t('share.dataGb', { n: sel.sim.data_gb })}</span> : <span>{t('share.unlimitedData')}</span>}
              {sel.sim.validity_days && <span>{t('share.validityDays', { count: sel.sim.validity_days })}</span>}
              {sel.sim.network_quality?.speed && <span className="flex items-center gap-0.5"><Wifi size={9} />{sel.sim.network_quality.speed}</span>}
            </p>
          </DetailCard>
        )}

        {/* Transport */}
        {(sel.getting_around || []).length > 0 && (
          <DetailCard title={t('share.gettingAroundTitle', { n: sel.getting_around.length })} icon={Bus} accent="text-cyan-700">
            <ul className="space-y-2">
              {sel.getting_around.map((opt, i) => (
                <li key={i} className="text-sm">
                  <p className="text-gray-800 font-medium">
                    {opt.name}
                    {opt.city && <span className="ml-1.5 text-xs text-indigo-600 font-semibold">{city(opt.city)}</span>}
                  </p>
                  <p className="text-xs text-gray-500">
                    {opt.type ? opt.type.replace(/_/g, ' ') : ''}
                    {opt.price_info ? ` · ${opt.price_info}` : ''}
                  </p>
                </li>
              ))}
            </ul>
          </DetailCard>
        )}

        {/* Tips */}
        {(sel.tips || []).length > 0 && (
          <DetailCard title={t('share.tipsTitle', { n: sel.tips.length })} icon={Lightbulb} accent="text-amber-700">
            <ul className="space-y-2">
              {sel.tips.map((tip, i) => (
                <li key={i} className="text-sm">
                  <p className="text-gray-800 font-medium">{tip.title}</p>
                  {tip.body && <p className="text-xs text-gray-500">{tip.body}</p>}
                </li>
              ))}
            </ul>
          </DetailCard>
        )}

        {/* Actions */}
        <div className="flex flex-col sm:flex-row gap-3">
          <button onClick={handleDownload} data-tid="share.download" disabled={downloading} aria-busy={downloading}
            className="flex-1 flex items-center justify-center gap-2 px-5 py-3 bg-teal-700 text-white font-semibold rounded-xl hover:bg-teal-800 transition-colors shadow-md text-sm disabled:opacity-70">
            {downloading ? <Loader2 size={15} className="animate-spin" /> : <Download size={15} />} {t('share.download')}
          </button>
          <Link to="/" data-tid="share.plan-own" className="flex-1 flex items-center justify-center gap-2 px-5 py-3 bg-white text-teal-700 font-semibold rounded-xl border border-teal-200 hover:bg-teal-50 transition-colors text-sm">
            {t('share.planOwnArrow')}
          </Link>
        </div>
        {downloadFailed && <p role="alert" className="text-center text-sm text-red-600">{t('share.downloadError')}</p>}
        <p className="text-center text-xs text-gray-400">{t('share.readOnly')}</p>
      </div>
      <AttributionFooter />
    </div>
  )
}
