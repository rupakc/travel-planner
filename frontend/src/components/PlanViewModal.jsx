import { useState } from 'react'
import {
  X, Plane, Hotel, MapPin, Smartphone, Calendar,
  Save, Trash2, Loader2, Check, PenLine, ExternalLink,
  ChevronDown, ChevronUp, DollarSign, Star, Lightbulb, Bus, Wifi
} from 'lucide-react'
import { computePlanCost, getBudgetStatus } from '../utils/planHelpers'

const SECTION_COLORS = {
  sky:    'bg-sky-50 border-b border-sky-100 text-sky-800',
  purple: 'bg-purple-50 border-b border-purple-100 text-purple-800',
  green:  'bg-green-50 border-b border-green-100 text-green-800',
  pink:   'bg-pink-50 border-b border-pink-100 text-pink-800',
  cyan:   'bg-cyan-50 border-b border-cyan-100 text-cyan-800',
  amber:  'bg-amber-50 border-b border-amber-100 text-amber-800',
  teal:   'bg-teal-50 border-b border-teal-100 text-teal-800',
}

function Section({ title, color, icon: Icon, children, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="border rounded-xl overflow-hidden mb-3">
      <button
        onClick={() => setOpen(v => !v)}
        className={`w-full flex items-center justify-between px-4 py-2.5 font-semibold text-sm ${SECTION_COLORS[color] ?? SECTION_COLORS.teal}`}
      >
        <span className="flex items-center gap-2"><Icon size={14} />{title}</span>
        {open ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
      </button>
      {open && <div className="p-3">{children}</div>}
    </div>
  )
}

export default function PlanViewModal({ plan, token, onClose, onSaved, onDeleted }) {
  const [name, setName]           = useState(plan.name)
  const [sel,  setSel]            = useState(() => ({
    flight: null, hotel: null, activities: [], sim: null, tips: [], getting_around: [],
    itinerary_notes: {}, itinerary_edits: {}, itinerary_slots: [],
    ...(plan.selections || {}),
  }))
  const [saving,   setSaving]   = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [msg,      setMsg]      = useState('')

  const sd = plan.search_data || {}
  const totalCost = computePlanCost(sel, sd)
  const budget = getBudgetStatus(totalCost, sd.budget_usd)

  const removeItem = (type, value) => {
    if (type === 'activities') {
      setSel(s => ({ ...s, activities: s.activities.filter(a => a.name !== value.name) }))
    } else if (type === 'tips') {
      setSel(s => ({ ...s, tips: (s.tips || []).filter(t => t.title !== value.title) }))
    } else if (type === 'getting_around') {
      setSel(s => ({ ...s, getting_around: (s.getting_around || []).filter(a => a.name !== value.name) }))
    } else if (type === 'itinerary_slots') {
      setSel(s => ({ ...s, itinerary_slots: (s.itinerary_slots || []).filter(sl => sl.key !== value.key) }))
    } else {
      setSel(s => ({ ...s, [type]: null }))
    }
  }

  const save = async () => {
    setSaving(true); setMsg('')
    try {
      const res = await fetch(`/api/plans/${plan.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ name, selections: sel }),
      })
      if (res.ok) {
        const updated = await res.json()
        setMsg('Saved ✓')
        onSaved?.(updated)
        setTimeout(() => setMsg(''), 2000)
      } else {
        setMsg('Save failed')
      }
    } catch { setMsg('Save failed') }
    finally { setSaving(false) }
  }

  const deletePlan = async () => {
    if (!confirm(`Delete "${name}"?`)) return
    setDeleting(true)
    try {
      await fetch(`/api/plans/${plan.id}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` },
      })
      onDeleted?.(plan.id)
      onClose()
    } finally { setDeleting(false) }
  }

  const hasSelections = sel.flight || sel.hotel || sel.activities?.length || sel.sim || sel.getting_around?.length || sel.tips?.length || sel.itinerary_slots?.length

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center sm:p-4">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={onClose} />

      {/* Modal — full-height bottom sheet on mobile, centered card on sm+ */}
      <div className="relative bg-white rounded-t-2xl sm:rounded-2xl shadow-2xl w-full sm:max-w-2xl h-[92vh] sm:h-auto sm:max-h-[90vh] flex flex-col overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 bg-gradient-to-r from-slate-500 to-slate-600 text-white shrink-0">
          <div className="flex-1 min-w-0 mr-3">
            <input
              value={name}
              onChange={e => setName(e.target.value)}
              className="bg-white/20 border border-white/30 rounded-lg px-3 py-1.5 text-white font-semibold text-sm w-full placeholder-white/60 focus:outline-none focus:ring-2 focus:ring-white/40"
              placeholder="Plan name…"
            />
            {sd.origin && (
              <p className="text-slate-300 text-xs mt-1">
                {sd.origin} → {sd.destination} · {sd.departure_date}{sd.return_date ? ` – ${sd.return_date}` : ''} · {sd.num_travelers || 1} traveler{(sd.num_travelers || 1) > 1 ? 's' : ''}
              </p>
            )}
            {totalCost > 0 && (
              <div className="flex items-center gap-2 mt-1.5">
                <span className="text-white font-bold text-sm">${totalCost.toLocaleString(undefined, {maximumFractionDigits:0})}</span>
                {budget && (
                  <span className={`text-[10px] font-medium px-2 py-0.5 rounded-full ${budget.status === 'under' ? 'bg-green-500/25 text-green-200' : 'bg-red-500/25 text-red-200'}`}>
                    <DollarSign size={9} className="inline -mt-0.5" /> {budget.label}
                  </span>
                )}
              </div>
            )}
          </div>
          <button onClick={onClose} className="text-white/80 hover:text-white shrink-0"><X size={20} /></button>
        </div>

        {/* Scrollable body */}
        <div className="flex-1 overflow-y-auto p-5">
          {!hasSelections && (
            <div className="text-center py-10 text-gray-400">
              <Calendar size={36} className="mx-auto mb-2 opacity-30" />
              <p className="text-sm">This plan has no saved selections yet.</p>
            </div>
          )}

          {/* Flight */}
          {sel.flight && (
            <Section title="Flight" color="sky" icon={Plane}>
              <div className="flex items-start justify-between">
                <div>
                  {sel.flight.outbound ? (
                    <>
                      <p className="text-xs text-gray-500 mb-0.5">Outbound: <span className="font-medium text-gray-700">{sel.flight.outbound.airline}</span>{sel.flight.outbound.flight_number && <span className="text-gray-400 ml-1">{sel.flight.outbound.flight_number}</span>} · {sel.flight.outbound.origin} → {sel.flight.outbound.destination}</p>
                      {sel.flight.return && <p className="text-xs text-gray-500 mb-0.5">Return: <span className="font-medium text-gray-700">{sel.flight.return.airline}</span>{sel.flight.return.flight_number && <span className="text-gray-400 ml-1">{sel.flight.return.flight_number}</span>} · {sel.flight.return.origin} → {sel.flight.return.destination}</p>}
                      <p className="text-xs font-semibold text-sky-700 mt-0.5">${Number(sel.flight.price_usd).toLocaleString()} {sel.flight.trip_type === 'round_trip' ? 'round-trip' : 'one-way'}</p>
                    </>
                  ) : (
                    <>
                      <p className="text-sm font-semibold text-gray-900">{sel.flight.airline} {sel.flight.flight_number || ''}</p>
                      <p className="text-xs text-gray-500">{sel.flight.origin} → {sel.flight.destination}</p>
                      {sel.flight.price_usd && <p className="text-xs font-medium text-sky-700 mt-0.5">${Number(sel.flight.price_usd).toLocaleString()}</p>}
                    </>
                  )}
                  {sel.flight.booking_url && (
                    <a href={sel.flight.booking_url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 text-xs text-sky-600 hover:text-sky-800 font-medium mt-1"><ExternalLink size={10} /> Book this flight</a>
                  )}
                </div>
                <button onClick={() => removeItem('flight')} className="p-1.5 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors">
                  <Trash2 size={14} />
                </button>
              </div>
            </Section>
          )}

          {/* Hotel */}
          {sel.hotel && (
            <Section title="Hotel" color="purple" icon={Hotel}>
              <div className="flex items-start justify-between">
                <div>
                  <p className="text-sm font-semibold text-gray-900">{sel.hotel.name}</p>
                  {sel.hotel.star_rating > 0 && (
                    <div className="flex items-center gap-1.5 mt-0.5">
                      <div className="flex">{[...Array(Math.round(sel.hotel.star_rating))].map((_, j) => <Star key={j} size={10} className="text-yellow-400 fill-yellow-400" />)}</div>
                      {sel.hotel.review_score && <span className="text-xs text-gray-400">{sel.hotel.review_score}/10</span>}
                    </div>
                  )}
                  <p className="text-xs text-gray-500 mt-0.5">{sel.hotel.location}</p>
                  {sel.hotel.price_per_night_usd && <p className="text-xs font-medium text-purple-700 mt-0.5">${sel.hotel.price_per_night_usd}/night{sel.hotel.total_price_usd ? ` · $${sel.hotel.total_price_usd.toLocaleString()} total` : ''}</p>}
                  {sel.hotel.booking_url && (
                    <a href={sel.hotel.booking_url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 text-xs text-purple-600 hover:text-purple-800 font-medium mt-1"><ExternalLink size={10} /> View & Book</a>
                  )}
                </div>
                <button onClick={() => removeItem('hotel')} className="p-1.5 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors">
                  <Trash2 size={14} />
                </button>
              </div>
            </Section>
          )}

          {/* Activities */}
          {sel.activities?.length > 0 && (
            <Section title={`Activities (${sel.activities.length})`} color="green" icon={MapPin}>
              <div className="space-y-2">
                {sel.activities.map((a, i) => (
                  <div key={i} className="flex items-start justify-between py-1.5 border-b border-gray-100 last:border-0">
                    <div className="flex-1 min-w-0 mr-2">
                      <p className="text-sm font-medium text-gray-900">{a.name}</p>
                      <div className="flex items-center gap-2 mt-0.5 text-xs text-gray-500">
                        {a.price_usd != null && <span>${a.price_usd}</span>}
                        {a.duration_hours && <span>{a.duration_hours}h</span>}
                        {a.location && <span className="truncate">{a.location}</span>}
                      </div>
                      {a.booking_url && (
                        <a href={a.booking_url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 text-xs text-green-600 hover:text-green-800 font-medium mt-0.5"><ExternalLink size={10} /> Book</a>
                      )}
                    </div>
                    <button onClick={() => removeItem('activities', a)} className="p-1.5 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors shrink-0">
                      <Trash2 size={13} />
                    </button>
                  </div>
                ))}
              </div>
            </Section>
          )}

          {/* SIM */}
          {sel.sim && (
            <Section title="SIM Card" color="pink" icon={Smartphone}>
              <div className="flex items-start justify-between">
                <div>
                  <p className="text-sm font-semibold text-gray-900">{sel.sim.provider}</p>
                  <p className="text-xs text-gray-500">{sel.sim.plan_name}</p>
                  <div className="flex items-center gap-2 mt-0.5 text-xs text-gray-500">
                    {sel.sim.price_usd != null && <span className="font-medium text-pink-700">${sel.sim.price_usd}</span>}
                    {sel.sim.data_gb && <span>{sel.sim.data_gb}GB</span>}
                    {sel.sim.validity_days && <span>{sel.sim.validity_days} days</span>}
                    {sel.sim.network_quality?.speed && <span className="flex items-center gap-0.5"><Wifi size={9}/>{sel.sim.network_quality.speed}</span>}
                    {sel.sim.network_quality?.coverage_rating && <span className={`px-1.5 py-0.5 rounded-full text-[10px] font-medium ${sel.sim.network_quality.coverage_rating === 'excellent' ? 'bg-green-100 text-green-700' : sel.sim.network_quality.coverage_rating === 'good' ? 'bg-blue-100 text-blue-700' : sel.sim.network_quality.coverage_rating === 'moderate' ? 'bg-yellow-100 text-yellow-700' : 'bg-red-100 text-red-700'}`}>{sel.sim.network_quality.coverage_rating}</span>}
                  </div>
                  {sel.sim.url && (
                    <a href={sel.sim.url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 text-xs text-pink-600 hover:text-pink-800 font-medium mt-1"><ExternalLink size={10} /> Get Plan</a>
                  )}
                </div>
                <button onClick={() => removeItem('sim')} className="p-1.5 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors">
                  <Trash2 size={14} />
                </button>
              </div>
            </Section>
          )}

          {/* Getting Around */}
          {sel.getting_around?.length > 0 && (
            <Section title={`Getting Around (${sel.getting_around.length})`} color="cyan" icon={Bus}>
              <div className="space-y-2">
                {sel.getting_around.map((opt, i) => (
                  <div key={i} className="flex items-start justify-between py-1.5 border-b border-gray-100 last:border-0">
                    <div className="flex-1 min-w-0 mr-2">
                      <p className="text-sm font-medium text-gray-900">{opt.name}</p>
                      <div className="flex items-center gap-2 mt-0.5 text-xs text-gray-500">
                        {opt.type && <span className="capitalize">{opt.type.replace(/_/g, ' ')}</span>}
                        {opt.scope && <span className="capitalize">{opt.scope.replace(/_/g, ' ')}</span>}
                      </div>
                      {opt.price_info && <p className="text-xs text-gray-500 mt-0.5">{opt.price_info}</p>}
                      {opt.booking_url && (
                        <a href={opt.booking_url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 text-xs text-cyan-600 hover:text-cyan-800 font-medium mt-0.5"><ExternalLink size={10} /> More Info</a>
                      )}
                    </div>
                    <button onClick={() => removeItem('getting_around', opt)} className="p-1.5 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors shrink-0">
                      <Trash2 size={13} />
                    </button>
                  </div>
                ))}
              </div>
            </Section>
          )}

          {/* Tips */}
          {sel.tips?.length > 0 && (
            <Section title={`Tips (${sel.tips.length})`} color="amber" icon={Lightbulb}>
              <div className="space-y-2">
                {sel.tips.map((t, i) => (
                  <div key={i} className="flex items-start justify-between py-1.5 border-b border-gray-100 last:border-0">
                    <div className="flex-1 min-w-0 mr-2">
                      <div className="flex items-center gap-1.5">
                        <p className="text-sm font-medium text-gray-900">{t.title}</p>
                        {t.severity && <span className={`px-1 py-0.5 rounded text-[10px] font-medium ${t.severity === 'danger' ? 'bg-red-100 text-red-700' : t.severity === 'warning' ? 'bg-yellow-100 text-yellow-700' : 'bg-blue-100 text-blue-700'}`}>{t.severity}</span>}
                      </div>
                      {t.body && <p className="text-xs text-gray-500 mt-0.5 line-clamp-2">{t.body}</p>}
                      {t.source_url && (
                        <a href={t.source_url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 text-xs text-amber-600 hover:text-amber-800 font-medium mt-0.5"><ExternalLink size={10} /> Source</a>
                      )}
                    </div>
                    <button onClick={() => removeItem('tips', t)} className="p-1.5 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors shrink-0">
                      <Trash2 size={13} />
                    </button>
                  </div>
                ))}
              </div>
            </Section>
          )}

          {/* Itinerary slots */}
          {sel.itinerary_slots?.length > 0 && (
            <Section title={`Itinerary Slots (${sel.itinerary_slots.length})`} color="teal" icon={Calendar}>
              <div className="space-y-2">
                {sel.itinerary_slots.map((slot, i) => (
                  <div key={i} className="flex items-start justify-between py-1.5 border-b border-gray-100 last:border-0">
                    <div className="flex-1 min-w-0 mr-2">
                      <div className="flex items-center gap-1.5 mb-0.5">
                        <span className="text-xs font-semibold text-teal-600">Day {slot.day_number}</span>
                        <span className="text-xs text-gray-400 capitalize">{slot.time_of_day}</span>
                      </div>
                      <p className="text-sm font-medium text-gray-900">{slot.activity}</p>
                      {slot.location && <p className="text-xs text-gray-500">{slot.location}</p>}
                      {sel.itinerary_notes?.[slot.key] && (
                        <p className="text-xs text-teal-600 italic mt-0.5">📝 {sel.itinerary_notes[slot.key]}</p>
                      )}
                    </div>
                    <button onClick={() => removeItem('itinerary_slots', slot)} className="p-1.5 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors shrink-0">
                      <Trash2 size={13} />
                    </button>
                  </div>
                ))}
              </div>
            </Section>
          )}
        </div>

        {/* Footer */}
        <div className="shrink-0 px-5 py-4 border-t border-gray-200 bg-gray-50 flex items-center justify-between gap-3">
          <button onClick={deletePlan} disabled={deleting}
            className="flex items-center gap-1.5 px-3 py-2 text-red-600 border border-red-200 rounded-lg text-sm font-medium hover:bg-red-50 transition-colors disabled:opacity-50">
            {deleting ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />} Delete
          </button>
          <div className="flex items-center gap-2 flex-1 justify-end">
            {msg && <span className={`text-sm font-medium ${msg.includes('fail') ? 'text-red-600' : 'text-green-600'}`}>{msg}</span>}
            <button onClick={onClose} className="px-4 py-2 text-gray-600 border border-gray-300 rounded-lg text-sm font-medium hover:bg-gray-100 transition-colors">
              Close
            </button>
            <button onClick={save} disabled={saving}
              className="flex items-center gap-1.5 px-4 py-2 bg-teal-600 text-white rounded-lg text-sm font-semibold hover:bg-teal-700 disabled:opacity-50 transition-all">
              {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />} Save Changes
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
