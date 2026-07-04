import { useState, useEffect, useCallback } from 'react'
import { useParams, Link } from 'react-router-dom'
import {
  Loader2, Download, Plane, Hotel, MapPin, Calendar, Users, Smartphone, Bus,
  PartyPopper, Star, Clock, DollarSign, Lightbulb, Wifi,
} from 'lucide-react'
import { computePlanCost } from '../utils/planHelpers'

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

function tripDates(sd) {
  if (!sd?.departure_date) return null
  const opts = { month: 'short', day: 'numeric', year: 'numeric' }
  const dep = new Date(`${sd.departure_date}T00:00:00`).toLocaleDateString(undefined, opts)
  if (!sd.return_date) return dep
  const ret = new Date(`${sd.return_date}T00:00:00`).toLocaleDateString(undefined, opts)
  return `${dep} → ${ret}`
}

function destinationLabel(sd) {
  if (sd?.destinations?.length > 1) return sd.destinations.join(' → ')
  return sd?.destination || 'Somewhere wonderful'
}

const city = (c) => String(c || '').split(',')[0].trim()

function fmtDuration(mins) {
  if (!mins) return null
  return `${Math.floor(mins / 60)}h ${mins % 60}m`
}

// One flight leg's detail line (works for outbound, return and multi-city legs)
function FlightRow({ tag, leg, price }) {
  if (!leg) return null
  return (
    <div className="flex items-start gap-2 text-sm">
      <span className="shrink-0 px-1.5 py-0.5 rounded bg-sky-100 text-sky-700 text-xs font-semibold mt-0.5">{tag}</span>
      <div className="min-w-0 flex-1">
        <p className="text-gray-800 font-medium">
          {leg.airline || 'Flight'}{leg.flight_number ? ` ${leg.flight_number}` : ''}
          {price != null && <span className="text-sky-700 font-bold"> · ${Number(price).toLocaleString()}</span>}
        </p>
        <p className="text-xs text-gray-500">
          {leg.origin} → {leg.destination}
          {leg.departure_date ? ` · ${leg.departure_date}` : ''}
          {leg.departure_time ? ` · ${leg.departure_time}–${leg.arrival_time || '?'}` : ''}
          {fmtDuration(leg.duration_minutes) ? ` · ${fmtDuration(leg.duration_minutes)}` : ''}
          {leg.stops != null ? ` · ${leg.stops === 0 ? 'non-stop' : `${leg.stops} stop${leg.stops > 1 ? 's' : ''}`}` : ''}
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

// Draws the poster onto a canvas and triggers a PNG download — no extra deps
function downloadCard(plan) {
  const sd = plan.search_data || {}
  const sel = plan.selections || {}
  const [c1, c2] = pickGradient(plan.name)
  const W = 1080, H = 1350
  const canvas = document.createElement('canvas')
  canvas.width = W
  canvas.height = H
  const ctx = canvas.getContext('2d')

  const grad = ctx.createLinearGradient(0, 0, W, H)
  grad.addColorStop(0, c1)
  grad.addColorStop(1, c2)
  ctx.fillStyle = grad
  ctx.fillRect(0, 0, W, H)

  ctx.fillStyle = 'rgba(255,255,255,0.12)'
  ctx.beginPath(); ctx.arc(W - 120, 140, 220, 0, Math.PI * 2); ctx.fill()
  ctx.beginPath(); ctx.arc(80, H - 160, 260, 0, Math.PI * 2); ctx.fill()

  ctx.fillStyle = 'rgba(255,255,255,0.85)'
  ctx.font = '600 40px system-ui, sans-serif'
  ctx.fillText('✈ Voyager Trip', 80, 120)

  ctx.fillStyle = '#ffffff'
  ctx.font = '700 76px system-ui, sans-serif'
  const dest = destinationLabel(sd)
  // Wrap the destination line if long
  const words = dest.split(' ')
  let line = '', y = 320
  for (const w of words) {
    const test = line ? `${line} ${w}` : w
    if (ctx.measureText(test).width > W - 160 && line) {
      ctx.fillText(line, 80, y); y += 92; line = w
    } else line = test
  }
  ctx.fillText(line, 80, y)

  ctx.fillStyle = 'rgba(255,255,255,0.9)'
  ctx.font = '400 44px system-ui, sans-serif'
  const dates = tripDates(sd)
  if (dates) ctx.fillText(dates, 80, y + 90)
  if (sd.origin) ctx.fillText(`from ${sd.origin}`, 80, y + 150)

  let statsY = y + 260
  ctx.font = '600 40px system-ui, sans-serif'
  const stats = []
  const legFlights = sel.flights || []
  if (legFlights.length) {
    const legTotal = legFlights.reduce((t, f) => t + (Number(f.price_usd) || 0), 0)
    stats.push(`✈️  ${legFlights.length} flight legs${legTotal ? ` — $${legTotal.toLocaleString()}` : ''}`)
  } else if (sel.flight) {
    const ob = sel.flight.outbound || sel.flight
    stats.push(`✈️  ${ob.airline || 'Flight picked'}${sel.flight.price_usd ? ` — $${Number(sel.flight.price_usd).toLocaleString()}` : ''}`)
  }
  if (sel.hotel?.name) stats.push(`🏨  ${sel.hotel.name}${sel.hotel.price_per_night_usd ? ` — $${sel.hotel.price_per_night_usd}/night` : ''}`)
  if (sel.itinerary?.days?.length) stats.push(`📅  ${sel.itinerary.days.length}-day itinerary inside`)
  else if (sel.itinerary_slots?.length) stats.push(`📅  ${sel.itinerary_slots.length} itinerary picks`)
  if (sel.activities?.length) stats.push(`🎯  ${sel.activities.length} activities planned`)
  if (sel.events?.length) stats.push(`🎉  ${sel.events.length} local events`)
  const totalCost = computePlanCost(sel, sd)
  if (totalCost > 0) stats.push(`💰  ~$${Math.round(totalCost).toLocaleString()} planned spend`)
  if ((sd.interests || []).length) stats.push(`✨  ${sd.interests.slice(0, 4).join(' · ')}`)
  for (const s of stats.slice(0, 6)) {
    ctx.fillText(s, 80, statsY)
    statsY += 72
  }

  ctx.fillStyle = 'rgba(255,255,255,0.75)'
  ctx.font = '400 34px system-ui, sans-serif'
  ctx.fillText(plan.name || 'My Trip Plan', 80, H - 90)

  const a = document.createElement('a')
  a.download = `${(plan.name || 'trip-card').replace(/[^a-z0-9]+/gi, '-').toLowerCase()}.png`
  a.href = canvas.toDataURL('image/png')
  a.click()
}

export default function SharePage() {
  const { token } = useParams()
  const [plan, setPlan] = useState(null)
  const [status, setStatus] = useState('loading')

  useEffect(() => {
    fetch(`/api/share/${encodeURIComponent(token)}`)
      .then(r => (r.ok ? r.json() : Promise.reject()))
      .then(data => { setPlan(data); setStatus('done') })
      .catch(() => setStatus('error'))
  }, [token])

  const handleDownload = useCallback(() => plan && downloadCard(plan), [plan])

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
        <h1 className="text-xl font-bold text-slate-800">This shared trip isn't available</h1>
        <p className="text-sm text-slate-500">The link may have been revoked or mistyped.</p>
        <Link to="/" className="mt-2 px-5 py-2.5 bg-teal-600 text-white text-sm font-semibold rounded-xl hover:bg-teal-700 transition-colors">Plan your own trip</Link>
      </div>
    )
  }

  const sd = plan.search_data || {}
  const sel = plan.selections || {}
  const [c1, c2] = pickGradient(plan.name)
  const travelers = sd.num_travelers || 1
  const totalCost = computePlanCost(sel, sd)
  const itinDays = sel.itinerary?.days || []
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
        <div className="rounded-3xl shadow-2xl overflow-hidden text-white relative" style={{ background: `linear-gradient(135deg, ${c1}, ${c2})` }}>
          <div className="absolute -top-16 -right-16 w-56 h-56 rounded-full bg-white/10" />
          <div className="absolute -bottom-20 -left-16 w-64 h-64 rounded-full bg-white/10" />
          <div className="relative p-8 space-y-5">
            <p className="text-sm font-semibold tracking-widest uppercase text-white/80">✈ Voyager Trip</p>
            <div>
              <h1 className="text-3xl font-bold leading-tight">{destinationLabel(sd)}</h1>
              {sd.origin && <p className="text-white/80 text-sm mt-1">from {sd.origin}</p>}
            </div>
            <div className="flex flex-wrap gap-x-4 gap-y-1.5 text-sm text-white/90">
              {tripDates(sd) && <span className="flex items-center gap-1.5"><Calendar size={13} />{tripDates(sd)}</span>}
              <span className="flex items-center gap-1.5"><Users size={13} />{travelers} traveler{travelers > 1 ? 's' : ''}</span>
              {totalCost > 0 && <span className="flex items-center gap-1.5"><DollarSign size={13} />~${Math.round(totalCost).toLocaleString()} planned</span>}
            </div>
            {(sd.interests || []).length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {sd.interests.map(i => (
                  <span key={i} className="px-2.5 py-1 rounded-full bg-white/20 text-xs font-medium">{i}</span>
                ))}
              </div>
            )}
            <div className="space-y-2 pt-2 border-t border-white/20 text-sm">
              {legFlights.length > 0 && <p className="flex items-center gap-2"><Plane size={14} className="shrink-0" />{legFlights.length} flight leg{legFlights.length > 1 ? 's' : ''} booked into the plan</p>}
              {!legFlights.length && sel.flight?.outbound?.airline && <p className="flex items-center gap-2"><Plane size={14} className="shrink-0" />{sel.flight.outbound.airline}{sel.flight.price_usd ? ` — $${Number(sel.flight.price_usd).toLocaleString()}` : ''}</p>}
              {sel.hotel?.name && <p className="flex items-center gap-2"><Hotel size={14} className="shrink-0" />{sel.hotel.name}</p>}
              {(sel.activities || []).length > 0 && <p className="flex items-center gap-2"><MapPin size={14} className="shrink-0" />{sel.activities.length} activities planned</p>}
              {itinDays.length > 0 && <p className="flex items-center gap-2"><Calendar size={14} className="shrink-0" />Full {itinDays.length}-day itinerary below</p>}
              {sel.sim?.provider && <p className="flex items-center gap-2"><Smartphone size={14} className="shrink-0" />{sel.sim.provider}</p>}
              {(sel.getting_around || []).length > 0 && <p className="flex items-center gap-2"><Bus size={14} className="shrink-0" />{sel.getting_around.length} transport picks</p>}
              {(sel.events || []).length > 0 && <p className="flex items-center gap-2"><PartyPopper size={14} className="shrink-0" />{sel.events.length} local event{sel.events.length > 1 ? 's' : ''}</p>}
            </div>
            <p className="text-white/70 text-xs pt-2">{plan.name}</p>
          </div>
        </div>

        {/* Flights */}
        {(legFlights.length > 0 || sel.flight) && (
          <DetailCard title="Flights" icon={Plane} accent="text-sky-700">
            <div className="space-y-3">
              {legFlights.length > 0
                ? legFlights.map((f, i) => (
                    <FlightRow key={i}
                      tag={`Leg ${(f.leg_index ?? i) + 1}`}
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
                          <FlightRow tag="Depart" leg={sel.flight.outbound} price={sel.flight.price_usd} />
                          {sel.flight.return && <FlightRow tag="Return" leg={sel.flight.return} />}
                        </>
                      )
                      : <FlightRow tag="Flight" leg={sel.flight} price={sel.flight.price_usd} />}
                  </>
                )}
              {legFlights.length > 1 && (
                <p className="text-xs font-semibold text-sky-700 pt-1 border-t border-gray-100">
                  ${legFlights.reduce((t, f) => t + (Number(f.price_usd) || 0), 0).toLocaleString()} total flights / person
                </p>
              )}
            </div>
          </DetailCard>
        )}

        {/* Hotel */}
        {sel.hotel && (
          <DetailCard title="Hotel" icon={Hotel} accent="text-purple-700">
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
              {sel.hotel.price_per_night_usd ? ` · $${Number(sel.hotel.price_per_night_usd).toLocaleString()}/night` : ''}
              {sel.hotel.total_price_usd ? ` · $${Number(sel.hotel.total_price_usd).toLocaleString()} total` : ''}
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
          <DetailCard title={`Day-by-Day Itinerary (${itinDays.length} days)`} icon={Calendar} accent="text-teal-700">
            <div className="space-y-4">
              {itinDays.map((day, i) => (
                <div key={i}>
                  <p className="text-xs font-bold text-teal-700 uppercase tracking-wide">
                    Day {day.day_number}{day.date ? ` · ${day.date}` : ''}{day.city ? ` · ${city(day.city)}` : ''}
                  </p>
                  {day.theme && <p className="text-xs text-gray-400 italic">{day.theme}</p>}
                  <ul className="mt-1.5 space-y-1">
                    {(day.slots || []).map((slot, j) => {
                      const key = `${day.day_number}-${slot.time_of_day}`
                      const edit = sel.itinerary_edits?.[key] || {}
                      const note = sel.itinerary_notes?.[key]
                      return (
                        <li key={j} className="flex items-start gap-2 text-sm text-gray-700">
                          <span className="shrink-0 w-20 text-xs text-gray-400 capitalize mt-0.5">{slot.time_of_day}</span>
                          <span className="min-w-0">
                            {edit.activity ?? slot.activity}
                            {(edit.location ?? slot.location) && <span className="text-gray-400 text-xs"> — {edit.location ?? slot.location}</span>}
                            {note && <span className="block text-xs text-teal-600 italic">📝 {note}</span>}
                          </span>
                        </li>
                      )
                    })}
                  </ul>
                </div>
              ))}
              {sel.itinerary?.total_estimated_cost_usd > 0 && (
                <p className="text-xs font-semibold text-teal-700 pt-2 border-t border-gray-100">
                  Est. itinerary cost: ${Number(sel.itinerary.total_estimated_cost_usd).toLocaleString()} / person
                </p>
              )}
            </div>
          </DetailCard>
        )}

        {/* Itinerary picks fallback (no full snapshot saved) */}
        {!itinDays.length && Object.keys(slotsByDay).length > 0 && (
          <DetailCard title="Itinerary Picks" icon={Calendar} accent="text-teal-700">
            <div className="space-y-3">
              {Object.keys(slotsByDay).sort((a, b) => a - b).map(dayNum => (
                <div key={dayNum}>
                  <p className="text-xs font-bold text-teal-700 uppercase tracking-wide">Day {dayNum}</p>
                  <ul className="mt-1 space-y-1">
                    {slotsByDay[dayNum].map((slot, j) => (
                      <li key={j} className="flex items-start gap-2 text-sm text-gray-700">
                        <span className="shrink-0 w-20 text-xs text-gray-400 capitalize mt-0.5">{slot.time_of_day}</span>
                        <span>{slot.activity}{slot.location && <span className="text-gray-400 text-xs"> — {slot.location}</span>}</span>
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
          <DetailCard title={`Activities (${sel.activities.length})`} icon={MapPin} accent="text-green-700">
            <ul className="space-y-2.5">
              {sel.activities.map((a, i) => (
                <li key={i} className="text-sm">
                  <p className="text-gray-800 font-medium">
                    {a.name}
                    {a.city && <span className="ml-1.5 text-xs text-indigo-600 font-semibold">{city(a.city)}</span>}
                  </p>
                  <p className="text-xs text-gray-500 flex flex-wrap items-center gap-x-2">
                    {a.category && <span className="capitalize">{a.category}</span>}
                    {a.duration_hours && <span className="flex items-center gap-0.5"><Clock size={9} />{a.duration_hours}h</span>}
                    {a.price_usd != null && <span>${a.price_usd}</span>}
                    {a.location && <span>{a.location}</span>}
                  </p>
                </li>
              ))}
            </ul>
          </DetailCard>
        )}

        {/* Events */}
        {(sel.events || []).length > 0 && (
          <DetailCard title={`Local Events (${sel.events.length})`} icon={PartyPopper} accent="text-fuchsia-700">
            <ul className="space-y-2.5">
              {sel.events.map((ev, i) => (
                <li key={i} className="text-sm">
                  <p className="text-gray-800 font-medium">
                    {ev.name}
                    {ev.city && <span className="ml-1.5 text-xs text-indigo-600 font-semibold">{city(ev.city)}</span>}
                  </p>
                  <p className="text-xs text-gray-500 flex flex-wrap items-center gap-x-2">
                    {ev.category && <span className="capitalize">{ev.category}</span>}
                    {ev.start_date && <span>{ev.start_date}{ev.end_date && ev.end_date !== ev.start_date ? ` – ${ev.end_date}` : ''}</span>}
                    {ev.price && <span>{ev.price}</span>}
                    {ev.location && <span>{ev.location}</span>}
                  </p>
                </li>
              ))}
            </ul>
          </DetailCard>
        )}

        {/* SIM */}
        {sel.sim && (
          <DetailCard title="Staying Connected" icon={Smartphone} accent="text-pink-700">
            <p className="text-sm font-medium text-gray-800">{sel.sim.provider} — {sel.sim.plan_name}</p>
            <p className="text-xs text-gray-500 mt-0.5 flex flex-wrap items-center gap-x-2">
              {sel.sim.price_usd != null && <span className="font-semibold text-pink-700">${sel.sim.price_usd}</span>}
              {sel.sim.data_gb ? <span>{sel.sim.data_gb}GB</span> : <span>Unlimited data</span>}
              {sel.sim.validity_days && <span>{sel.sim.validity_days} days</span>}
              {sel.sim.network_quality?.speed && <span className="flex items-center gap-0.5"><Wifi size={9} />{sel.sim.network_quality.speed}</span>}
            </p>
          </DetailCard>
        )}

        {/* Transport */}
        {(sel.getting_around || []).length > 0 && (
          <DetailCard title={`Getting Around (${sel.getting_around.length})`} icon={Bus} accent="text-cyan-700">
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
          <DetailCard title={`Good to Know (${sel.tips.length})`} icon={Lightbulb} accent="text-amber-700">
            <ul className="space-y-2">
              {sel.tips.map((t, i) => (
                <li key={i} className="text-sm">
                  <p className="text-gray-800 font-medium">{t.title}</p>
                  {t.body && <p className="text-xs text-gray-500">{t.body}</p>}
                </li>
              ))}
            </ul>
          </DetailCard>
        )}

        {/* Actions */}
        <div className="flex flex-col sm:flex-row gap-3">
          <button onClick={handleDownload}
            className="flex-1 flex items-center justify-center gap-2 px-5 py-3 bg-teal-600 text-white font-semibold rounded-xl hover:bg-teal-700 transition-colors shadow-md text-sm">
            <Download size={15} /> Download trip card
          </button>
          <Link to="/" className="flex-1 flex items-center justify-center gap-2 px-5 py-3 bg-white text-teal-700 font-semibold rounded-xl border border-teal-200 hover:bg-teal-50 transition-colors text-sm">
            Plan your own trip →
          </Link>
        </div>
        <p className="text-center text-xs text-gray-400">Shared read-only — personal details are never included.</p>
      </div>
    </div>
  )
}
