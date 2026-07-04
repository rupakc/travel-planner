import { useState, useEffect, useCallback } from 'react'
import { useParams, Link } from 'react-router-dom'
import { Loader2, Download, Plane, Hotel, MapPin, Calendar, Users, Smartphone, Bus, PartyPopper } from 'lucide-react'

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
  if (sel.flight) stats.push('✈️  Flight picked')
  if (sel.hotel?.name) stats.push(`🏨  ${sel.hotel.name}`)
  if (sel.activities?.length) stats.push(`🎯  ${sel.activities.length} activities planned`)
  if (sel.itinerary_slots?.length) stats.push(`📅  ${sel.itinerary_slots.length} itinerary picks`)
  if (sel.events?.length) stats.push(`🎉  ${sel.events.length} local events`)
  if ((sd.interests || []).length) stats.push(`✨  ${sd.interests.slice(0, 4).join(' · ')}`)
  for (const s of stats.slice(0, 5)) {
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

  return (
    <div className="min-h-screen bg-gradient-to-br from-sky-100 via-teal-50 to-emerald-100 py-10 px-4">
      <div className="max-w-lg mx-auto">
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
            </div>
            {(sd.interests || []).length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {sd.interests.map(i => (
                  <span key={i} className="px-2.5 py-1 rounded-full bg-white/20 text-xs font-medium">{i}</span>
                ))}
              </div>
            )}
            <div className="space-y-2 pt-2 border-t border-white/20 text-sm">
              {sel.flight?.outbound?.airline && <p className="flex items-center gap-2"><Plane size={14} className="shrink-0" />{sel.flight.outbound.airline}{sel.flight.price_usd ? ` — $${Number(sel.flight.price_usd).toLocaleString()}` : ''}</p>}
              {sel.hotel?.name && <p className="flex items-center gap-2"><Hotel size={14} className="shrink-0" />{sel.hotel.name}</p>}
              {(sel.activities || []).length > 0 && <p className="flex items-center gap-2"><MapPin size={14} className="shrink-0" />{sel.activities.length} activities planned</p>}
              {sel.sim?.provider && <p className="flex items-center gap-2"><Smartphone size={14} className="shrink-0" />{sel.sim.provider}</p>}
              {(sel.getting_around || []).length > 0 && <p className="flex items-center gap-2"><Bus size={14} className="shrink-0" />{sel.getting_around.length} transport picks</p>}
              {(sel.events || []).length > 0 && <p className="flex items-center gap-2"><PartyPopper size={14} className="shrink-0" />{sel.events.length} local event{sel.events.length > 1 ? 's' : ''}</p>}
            </div>
            <p className="text-white/70 text-xs pt-2">{plan.name}</p>
          </div>
        </div>

        {/* Highlighted activities */}
        {(sel.activities || []).length > 0 && (
          <div className="mt-6 bg-white rounded-2xl shadow-lg p-5">
            <h2 className="text-sm font-bold text-gray-700 mb-3">Trip highlights</h2>
            <ul className="space-y-2">
              {sel.activities.slice(0, 8).map((a, i) => (
                <li key={i} className="flex items-start gap-2 text-sm text-gray-600">
                  <span className="text-teal-500 mt-0.5">•</span>
                  <span>{a.name}{a.price_usd ? <span className="text-gray-400"> — ${a.price_usd}</span> : null}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Actions */}
        <div className="mt-6 flex flex-col sm:flex-row gap-3">
          <button onClick={handleDownload}
            className="flex-1 flex items-center justify-center gap-2 px-5 py-3 bg-teal-600 text-white font-semibold rounded-xl hover:bg-teal-700 transition-colors shadow-md text-sm">
            <Download size={15} /> Download trip card
          </button>
          <Link to="/" className="flex-1 flex items-center justify-center gap-2 px-5 py-3 bg-white text-teal-700 font-semibold rounded-xl border border-teal-200 hover:bg-teal-50 transition-colors text-sm">
            Plan your own trip →
          </Link>
        </div>
        <p className="text-center text-xs text-gray-400 mt-4">Shared read-only — personal details are never included.</p>
      </div>
    </div>
  )
}
