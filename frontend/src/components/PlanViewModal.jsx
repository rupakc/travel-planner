import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { fmtNumber } from '../i18n/format'
import {
  X, Plane, Hotel, MapPin, Smartphone, Calendar,
  Save, Trash2, Loader2, Check, PenLine, ExternalLink,
  ChevronDown, ChevronUp, DollarSign, Star, Lightbulb, Bus, Wifi,
  PartyPopper, Share2, Footprints
} from 'lucide-react'
import WatchFareButton from './alerts/WatchFareButton'
import WatchTripButton from './alerts/WatchTripButton'
import { tripFromPlan } from '../utils/fareWatch'
import { QuickWatchHotel, QuickWatchActivity } from './alerts2/QuickWatchFor'
import { ActivityTripContext } from './alerts/activityTripContext'
import { computePlanCost, getBudgetStatus } from '../utils/planHelpers'
import { enumLabel } from '../utils/enumLabel'
import PlanExport from './PlanExport'
import { safeUrl } from '../utils/planPrint'
import { arrangeItinerary, slotKey } from '../utils/itineraryLayout'
import { scheduleDays, timeRange } from '../utils/schedule'

const SECTION_COLORS = {
  sky:    'bg-sky-50 border-b border-sky-100 text-sky-800',
  purple: 'bg-purple-50 border-b border-purple-100 text-purple-800',
  green:  'bg-green-50 border-b border-green-100 text-green-800',
  pink:   'bg-pink-50 border-b border-pink-100 text-pink-800',
  cyan:   'bg-cyan-50 border-b border-cyan-100 text-cyan-800',
  amber:  'bg-amber-50 border-b border-amber-100 text-amber-800',
  teal:   'bg-teal-50 border-b border-teal-100 text-teal-800',
  fuchsia:'bg-fuchsia-50 border-b border-fuchsia-100 text-fuchsia-800',
}

// Money: whole dollars for the total, up to cents for item prices
const usd0 = (n) => fmtNumber(Number(n), { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })
const usdX = (n) => fmtNumber(Number(n), { style: 'currency', currency: 'USD', minimumFractionDigits: 0, maximumFractionDigits: 2 })

function Section({ title, tid, color, icon: Icon, children, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="border rounded-xl overflow-hidden mb-3">
      <button
        onClick={() => setOpen(v => !v)}
        data-tid={`plan.section-${tid}`}
        className={`w-full flex items-center justify-between px-4 py-2.5 font-semibold text-sm ${SECTION_COLORS[color] ?? SECTION_COLORS.teal}`}
      >
        <span className="flex items-center gap-2"><Icon size={14} />{title}</span>
        {open ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
      </button>
      {open && <div className="p-3">{children}</div>}
    </div>
  )
}

// `inline`: the plan body inside a page (the trip screen's Overview) instead
// of a modal: no backdrop, no dialog role, no close buttons; the page owns the
// title and Delete.
export default function PlanViewModal({ plan, token, onClose, onSaved, onDeleted, inline = false }) {
  const { t } = useTranslation('plan')
  const tod = (v) => t(`modal.timeOfDay.${v}`, { defaultValue: v })
  const [name, setName]           = useState(plan.name)
  const [sel,  setSel]            = useState(() => ({
    flight: null, flights: [], hotel: null, activities: [], sim: null, tips: [], getting_around: [], events: [], walking_tours: [],
    itinerary_notes: {}, itinerary_edits: {}, itinerary_slots: [],
    ...(plan.selections || {}),
  }))
  const [saving,   setSaving]   = useState(false)
  const [sharing,  setSharing]  = useState(false)
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
    } else if (type === 'walking_tours') {
      setSel(s => ({ ...s, walking_tours: (s.walking_tours || []).filter(t => t.url !== value.url) }))
    } else if (type === 'events') {
      setSel(s => ({ ...s, events: (s.events || []).filter(e => e.name !== value.name) }))
    } else if (type === 'itinerary_slots') {
      setSel(s => ({ ...s, itinerary_slots: (s.itinerary_slots || []).filter(sl => sl.key !== value.key) }))
    } else if (type === 'flights') {
      setSel(s => ({ ...s, flights: (s.flights || []).filter(f => f !== value) }))
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
        setMsg('saved')
        onSaved?.(updated)
        setTimeout(() => setMsg(''), 2000)
      } else {
        setMsg('saveFailed')
      }
    } catch { setMsg('saveFailed') }
    finally { setSaving(false) }
  }

  const sharePlan = async () => {
    setSharing(true); setMsg('')
    try {
      const res = await fetch(`/api/plans/${plan.id}/share`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      })
      if (!res.ok) throw new Error()
      const { share_token } = await res.json()
      const url = `${window.location.origin}/share/${share_token}`
      try { await navigator.clipboard.writeText(url) } catch { /* clipboard may be unavailable */ }
      setMsg('shared')
      setTimeout(() => setMsg(''), 4000)
    } catch { setMsg('shareFailed') }
    finally { setSharing(false) }
  }

  const deletePlan = async () => {
    if (!confirm(t('modal.confirmDelete', { name }))) return
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

  const hasSelections = sel.flight || sel.flights?.length || sel.hotel || sel.activities?.length || sel.sim || sel.getting_around?.length || sel.tips?.length || sel.events?.length || sel.walking_tours?.length || sel.itinerary_slots?.length

  const card = (
      <>
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 bg-gradient-to-r from-slate-500 to-slate-600 text-white shrink-0">
          <div className="flex-1 min-w-0 mr-3">
            {!inline && <input
              value={name}
              onChange={e => setName(e.target.value)}
              data-tid="plan.name-input"
              className="bg-white/20 border border-white/30 rounded-lg px-3 py-1.5 text-white font-semibold text-sm w-full placeholder-white/60 focus:outline-none focus:ring-2 focus:ring-white/40"
              placeholder={t('modal.namePlaceholder')}
            />}
            {sd.origin && (
              <p className="text-slate-300 text-xs mt-1">
                {t('modal.trip', { origin: sd.origin, destination: sd.destination, dates: `${sd.departure_date}${sd.return_date ? ` – ${sd.return_date}` : ''}`, count: sd.num_travelers || 1 })}
              </p>
            )}
            <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1">
              <WatchFareButton variant="onDark" trip={tripFromPlan(plan)} source="plan_view" label={t('modal.watchFare')} />
              <WatchTripButton variant="onDark" plan={plan} source="plan_view" />
            </div>
            {totalCost > 0 && (
              <div className="flex items-center gap-2 mt-1.5">
                <span className="text-white font-bold text-sm">{usd0(totalCost)}</span>
                {budget && (
                  <span className={`text-[10px] font-medium px-2 py-0.5 rounded-full ${budget.status === 'under' ? 'bg-green-500/25 text-green-200' : 'bg-red-500/25 text-red-200'}`}>
                    <DollarSign size={9} className="inline -mt-0.5" /> {budget.label}
                  </span>
                )}
              </div>
            )}
          </div>
          {!inline && <button onClick={onClose} data-tid="plan.modal-close-x" aria-label={t('modal.close')} className="text-white/80 hover:text-white shrink-0"><X size={20} /></button>}
        </div>

        {/* Scrollable body */}
        <div className={inline ? 'p-4 sm:p-5' : 'flex-1 overflow-y-auto p-5'}>
          {!hasSelections && (
            <div className="text-center py-10 text-gray-400">
              <Calendar size={36} className="mx-auto mb-2 opacity-30" />
              <p className="text-sm">{t('modal.empty')}</p>
            </div>
          )}

          <PlanExport planName={name} planId={plan.id} searchData={sd} selections={sel} source="saved_plan" className="mb-4" />

          {/* Flight */}
          {sel.flight && (
            <Section title={t('modal.section.flight')} tid="flight" color="sky" icon={Plane}>
              <div className="flex items-start justify-between">
                <div>
                  {sel.flight.outbound ? (
                    <>
                      <p className="text-xs text-gray-500 mb-0.5">{t('modal.flight.outbound')} <span className="font-medium text-gray-700">{sel.flight.outbound.airline}</span>{sel.flight.outbound.flight_number && <span className="text-gray-400 ml-1">{sel.flight.outbound.flight_number}</span>} · {sel.flight.outbound.origin} → {sel.flight.outbound.destination}</p>
                      {sel.flight.return && <p className="text-xs text-gray-500 mb-0.5">{t('modal.flight.return')} <span className="font-medium text-gray-700">{sel.flight.return.airline}</span>{sel.flight.return.flight_number && <span className="text-gray-400 ml-1">{sel.flight.return.flight_number}</span>} · {sel.flight.return.origin} → {sel.flight.return.destination}</p>}
                      <p className="text-xs font-semibold text-sky-700 mt-0.5">{t(sel.flight.trip_type === 'round_trip' ? 'modal.flight.roundTrip' : 'modal.flight.oneWay', { price: usdX(sel.flight.price_usd) })}</p>
                    </>
                  ) : (
                    <>
                      <p className="text-sm font-semibold text-gray-900">{sel.flight.airline} {sel.flight.flight_number || ''}</p>
                      <p className="text-xs text-gray-500">{sel.flight.origin} → {sel.flight.destination}</p>
                      {sel.flight.price_usd && <p className="text-xs font-medium text-sky-700 mt-0.5">{usdX(sel.flight.price_usd)}</p>}
                    </>
                  )}
                  {sel.flight.booking_url && (
                    <a href={sel.flight.booking_url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 text-xs text-sky-600 hover:text-sky-800 font-medium mt-1"><ExternalLink size={10} /> {t('modal.flight.bookThis')}</a>
                  )}
                </div>
                <button data-tid="plan.remove-flight" aria-label={t('modal.delete')} onClick={() => removeItem('flight')} className="p-1.5 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors">
                  <Trash2 size={14} />
                </button>
              </div>
            </Section>
          )}

          {/* Multi-city flights (one per leg) */}
          {sel.flights?.length > 0 && (
            <Section title={t('modal.section.flights', { count: sel.flights.length })} tid="flights" color="sky" icon={Plane} defaultOpen>
              <div className="space-y-2">
                {sel.flights.map((f, i) => (
                  <div key={i} className="flex items-start justify-between py-1.5 border-b border-gray-100 last:border-0">
                    <div className="flex-1 min-w-0 mr-2">
                      <p className="text-xs text-gray-500">
                        <span className="font-semibold text-sky-700">{t('modal.flight.leg', { n: (f.leg_index ?? i) + 1 })}</span>{' '}
                        <span className="font-medium text-gray-700">{f.outbound?.airline || f.airline}</span>
                        {(f.outbound?.flight_number || f.flight_number) && <span className="text-gray-400 ml-1">{f.outbound?.flight_number || f.flight_number}</span>}
                      </p>
                      <p className="text-xs text-gray-500 mt-0.5">
                        {String(f.leg_from || f.outbound?.origin || '').split(',')[0]} → {String(f.leg_to || f.outbound?.destination || '').split(',')[0]}
                        {f.leg_date ? ` · ${f.leg_date}` : ''}
                        {f.price_usd != null && <span className="font-semibold text-sky-700"> · {usdX(f.price_usd)}</span>}
                      </p>
                      {f.booking_url && (
                        <a href={f.booking_url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 text-xs text-sky-600 hover:text-sky-800 font-medium mt-0.5"><ExternalLink size={10} /> {t('modal.book')}</a>
                      )}
                    </div>
                    <button data-tid="plan.remove-flights" aria-label={t('modal.delete')} onClick={() => removeItem('flights', f)} className="p-1.5 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors shrink-0">
                      <Trash2 size={13} />
                    </button>
                  </div>
                ))}
              </div>
            </Section>
          )}

          {/* Hotel */}
          {sel.hotel && (
            <Section title={t('modal.section.hotel')} tid="hotel" color="purple" icon={Hotel}>
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
                  {sel.hotel.price_per_night_usd && <p className="text-xs font-medium text-purple-700 mt-0.5">{sel.hotel.total_price_usd ? t('modal.hotel.perNightTotal', { price: usdX(sel.hotel.price_per_night_usd), total: usdX(sel.hotel.total_price_usd) }) : t('modal.hotel.perNight', { price: usdX(sel.hotel.price_per_night_usd) })}</p>}
                  {sel.hotel.booking_url && (
                    <a href={sel.hotel.booking_url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 text-xs text-purple-600 hover:text-purple-800 font-medium mt-1"><ExternalLink size={10} /> {t('modal.hotel.viewBook')}</a>
                  )}
                  <div className="mt-1"><QuickWatchHotel hotel={sel.hotel} searchData={sd} planId={plan.id ?? null} surface="results" /></div>
                </div>
                <button data-tid="plan.remove-hotel" aria-label={t('modal.delete')} onClick={() => removeItem('hotel')} className="p-1.5 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors">
                  <Trash2 size={14} />
                </button>
              </div>
            </Section>
          )}

          {/* Activities */}
          {sel.activities?.length > 0 && (
            <Section title={t('modal.section.activities', { count: sel.activities.length })} tid="activities" color="green" icon={MapPin}>
              <div className="space-y-2">
                {sel.activities.map((a, i) => (
                  <div key={i} className="flex items-start justify-between py-1.5 border-b border-gray-100 last:border-0">
                    <div className="flex-1 min-w-0 mr-2">
                      <p className="text-sm font-medium text-gray-900">{a.name}</p>
                      <div className="flex items-center gap-2 mt-0.5 text-xs text-gray-500">
                        {a.price_usd != null && <span>{usdX(a.price_usd)}</span>}
                        {a.duration_hours && <span>{t('modal.activity.hours', { hours: a.duration_hours })}</span>}
                        {a.location && <span className="truncate">{a.location}</span>}
                      </div>
                      {a.booking_url && (
                        <a href={a.booking_url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 text-xs text-green-600 hover:text-green-800 font-medium mt-0.5"><ExternalLink size={10} /> {t('modal.book')}</a>
                      )}
                      <div className="mt-1">
                        <ActivityTripContext.Provider value={{ searchData: sd, itinerary: sel.itinerary || null }}>
                          <QuickWatchActivity activity={a} planId={plan.id ?? null} surface="results" />
                        </ActivityTripContext.Provider>
                      </div>
                    </div>
                    <button data-tid="plan.remove-activities" aria-label={t('modal.delete')} onClick={() => removeItem('activities', a)} className="p-1.5 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors shrink-0">
                      <Trash2 size={13} />
                    </button>
                  </div>
                ))}
              </div>
            </Section>
          )}

          {/* SIM */}
          {sel.sim && (
            <Section title={t('modal.section.sim')} tid="sim" color="pink" icon={Smartphone}>
              <div className="flex items-start justify-between">
                <div>
                  <p className="text-sm font-semibold text-gray-900">{sel.sim.provider}</p>
                  <p className="text-xs text-gray-500">{sel.sim.plan_name}</p>
                  <div className="flex items-center gap-2 mt-0.5 text-xs text-gray-500">
                    {sel.sim.price_usd != null && <span className="font-medium text-pink-700">{usdX(sel.sim.price_usd)}</span>}
                    {sel.sim.data_gb && <span>{t('modal.sim.data', { gb: sel.sim.data_gb })}</span>}
                    {sel.sim.validity_days && <span>{t('modal.sim.days', { count: sel.sim.validity_days })}</span>}
                    {sel.sim.network_quality?.speed && <span className="flex items-center gap-0.5"><Wifi size={9}/>{sel.sim.network_quality.speed}</span>}
                    {sel.sim.network_quality?.coverage_rating && <span className={`px-1.5 py-0.5 rounded-full text-[10px] font-medium ${sel.sim.network_quality.coverage_rating === 'excellent' ? 'bg-green-100 text-green-700' : sel.sim.network_quality.coverage_rating === 'good' ? 'bg-blue-100 text-blue-700' : sel.sim.network_quality.coverage_rating === 'moderate' ? 'bg-yellow-100 text-yellow-700' : 'bg-red-100 text-red-700'}`}>{enumLabel('coverage', sel.sim.network_quality.coverage_rating)}</span>}
                  </div>
                  {sel.sim.url && (
                    <a href={sel.sim.url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 text-xs text-pink-600 hover:text-pink-800 font-medium mt-1"><ExternalLink size={10} /> {t('modal.sim.getPlan')}</a>
                  )}
                </div>
                <button data-tid="plan.remove-sim" aria-label={t('modal.delete')} onClick={() => removeItem('sim')} className="p-1.5 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors">
                  <Trash2 size={14} />
                </button>
              </div>
            </Section>
          )}

          {/* Getting Around */}
          {sel.getting_around?.length > 0 && (
            <Section title={t('modal.section.gettingAround', { count: sel.getting_around.length })} tid="getting-around" color="cyan" icon={Bus}>
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
                        <a href={opt.booking_url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 text-xs text-cyan-600 hover:text-cyan-800 font-medium mt-0.5"><ExternalLink size={10} /> {t('modal.moreInfo')}</a>
                      )}
                    </div>
                    <button data-tid="plan.remove-getting-around" aria-label={t('modal.delete')} onClick={() => removeItem('getting_around', opt)} className="p-1.5 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors shrink-0">
                      <Trash2 size={13} />
                    </button>
                  </div>
                ))}
              </div>
            </Section>
          )}

          {/* Tips */}
          {sel.tips?.length > 0 && (
            <Section title={t('modal.section.tips', { count: sel.tips.length })} tid="tips" color="amber" icon={Lightbulb}>
              <div className="space-y-2">
                {sel.tips.map((t, i) => (
                  <div key={i} className="flex items-start justify-between py-1.5 border-b border-gray-100 last:border-0">
                    <div className="flex-1 min-w-0 mr-2">
                      <div className="flex items-center gap-1.5">
                        <p className="text-sm font-medium text-gray-900">{t.title}</p>
                        {t.severity && <span className={`px-1 py-0.5 rounded text-[10px] font-medium ${t.severity === 'danger' ? 'bg-red-100 text-red-700' : t.severity === 'warning' ? 'bg-yellow-100 text-yellow-700' : 'bg-blue-100 text-blue-700'}`}>{enumLabel('severity', t.severity)}</span>}
                      </div>
                      {t.body && <p className="text-xs text-gray-500 mt-0.5 line-clamp-2">{t.body}</p>}
                      {t.source_url && (
                        <a href={t.source_url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 text-xs text-amber-600 hover:text-amber-800 font-medium mt-0.5"><ExternalLink size={10} /> {t('modal.source')}</a>
                      )}
                    </div>
                    <button data-tid="plan.remove-tips" aria-label={t('modal.delete')} onClick={() => removeItem('tips', t)} className="p-1.5 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors shrink-0">
                      <Trash2 size={13} />
                    </button>
                  </div>
                ))}
              </div>
            </Section>
          )}

          {/* Events */}
          {sel.events?.length > 0 && (
            <Section title={t('modal.section.events', { count: sel.events.length })} tid="events" color="fuchsia" icon={PartyPopper}>
              <div className="space-y-2">
                {sel.events.map((ev, i) => (
                  <div key={i} className="flex items-start justify-between py-1.5 border-b border-gray-100 last:border-0">
                    <div className="flex-1 min-w-0 mr-2">
                      <p className="text-sm font-medium text-gray-900">{ev.name}</p>
                      <div className="flex items-center gap-2 mt-0.5 text-xs text-gray-500">
                        {ev.category && <span className="capitalize">{ev.category}</span>}
                        {ev.start_date && <span>{ev.start_date}{ev.end_date && ev.end_date !== ev.start_date ? ` – ${ev.end_date}` : ''}</span>}
                        {ev.price && <span>{ev.price}</span>}
                      </div>
                      {ev.location && <p className="text-xs text-gray-500 mt-0.5">{ev.location}</p>}
                    </div>
                    <button data-tid="plan.remove-events" aria-label={t('modal.delete')} onClick={() => removeItem('events', ev)} className="p-1.5 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors shrink-0">
                      <Trash2 size={13} />
                    </button>
                  </div>
                ))}
              </div>
            </Section>
          )}

          {/* Walking tours */}
          {sel.walking_tours?.length > 0 && (
            <Section title={t('modal.section.walkingTours', { count: sel.walking_tours.length })} tid="walking-tours" color="green" icon={Footprints}>
              <div className="space-y-2">
                {(sel.walking_tours || []).map((t, i) => {
                  const href = safeUrl(t.url)
                  return (
                    <div key={t.url || i} className="flex items-start justify-between py-1.5 border-b border-gray-100 last:border-0">
                      <div className="flex-1 min-w-0 mr-2">
                        {href ? (
                          <a href={href} target="_blank" rel="noopener noreferrer" className="text-sm font-medium text-gray-900 hover:text-green-700 inline-flex items-center gap-1">
                            {t.name}<ExternalLink size={11} className="shrink-0" />
                          </a>
                        ) : (
                          <p className="text-sm font-medium text-gray-900">{t.name}</p>
                        )}
                        <div className="flex items-center gap-2 mt-0.5 text-xs text-gray-500">
                          {t.provider && <span>{t.provider}</span>}
                          {t.city && <span>{t.city}</span>}
                        </div>
                      </div>
                      <button data-tid="plan.remove-walking-tours" aria-label={t('modal.delete')} onClick={() => removeItem('walking_tours', t)} className="p-1.5 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors shrink-0">
                        <Trash2 size={13} />
                      </button>
                    </div>
                  )
                })}
              </div>
            </Section>
          )}

          {/* Itinerary slots */}
          {sel.itinerary_slots?.length > 0 && (
            <Section title={t('modal.section.itinerarySlots', { count: sel.itinerary_slots.length })} tid="itinerary-slots" color="teal" icon={Calendar}>
              <div className="space-y-2">
                {sel.itinerary_slots.map((slot, i) => (
                  <div key={i} className="flex items-start justify-between py-1.5 border-b border-gray-100 last:border-0">
                    <div className="flex-1 min-w-0 mr-2">
                      <div className="flex items-center gap-1.5 mb-0.5">
                        <span className="text-xs font-semibold text-teal-600">{t('modal.day', { n: slot.day_number })}</span>
                        <span className="text-xs text-gray-400 capitalize">{tod(slot.time_of_day)}</span>
                        {timeRange(slot) && <span className="text-xs text-teal-600">{timeRange(slot)}</span>}
                      </div>
                      <p className="text-sm font-medium text-gray-900">{slot.activity}</p>
                      {slot.location && <p className="text-xs text-gray-500">{slot.location}</p>}
                      {sel.itinerary_notes?.[slot.key] && (
                        <p className="text-xs text-teal-600 italic mt-0.5">📝 {sel.itinerary_notes[slot.key]}</p>
                      )}
                    </div>
                    <button data-tid="plan.remove-itinerary-slots" aria-label={t('modal.delete')} onClick={() => removeItem('itinerary_slots', slot)} className="p-1.5 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors shrink-0">
                      <Trash2 size={13} />
                    </button>
                  </div>
                ))}
              </div>
            </Section>
          )}
          {/* Full itinerary snapshot */}
          {sel.itinerary?.days?.length > 0 && (
            <Section title={t('modal.section.fullItinerary', { count: sel.itinerary.days.length })} tid="full-itinerary" color="teal" icon={Calendar}>
              <div className="space-y-3">
                {scheduleDays(arrangeItinerary(sel.itinerary, sel.itinerary_layout, sel.itinerary_edits).days, sel.itinerary_edits).map((day, i) => (
                  <div key={i}>
                    <p className="text-xs font-bold text-teal-700">
                      {t('modal.day', { n: day.day_number })}{day.date ? ` · ${day.date}` : ''}{day.city ? ` · ${String(day.city).split(',')[0]}` : ''}{day.theme ? ` — ${day.theme}` : ''}
                    </p>
                    <ul className="mt-1 space-y-0.5">
                      {(day.slots || []).map((slot, j) => {
                        const key = slot.key ?? slotKey(day.day_number, slot.time_of_day)
                        const edit = sel.itinerary_edits?.[key] || {}
                        return (
                          <li key={j} className="text-xs text-gray-600">
                            <span className="capitalize text-gray-400">{tod(slot.time_of_day)}</span>
                            {timeRange(slot) && <span className="text-gray-400 tabular-nums"> {timeRange(slot)}</span>}
                            <span className="text-gray-400">:</span> {edit.activity || slot.activity}
                            {sel.itinerary_notes?.[key] && <span className="text-teal-600 italic"> — 📝 {sel.itinerary_notes[key]}</span>}
                          </li>
                        )
                      })}
                    </ul>
                  </div>
                ))}
              </div>
            </Section>
          )}
        </div>

        {/* Footer */}
        <div className="shrink-0 px-5 py-4 border-t border-gray-200 bg-gray-50 flex items-center justify-between gap-3">
          {!inline && <button onClick={deletePlan} disabled={deleting} data-tid="plan.delete"
            className="flex items-center gap-1.5 px-3 py-2 text-red-600 border border-red-200 rounded-lg text-sm font-medium hover:bg-red-50 transition-colors disabled:opacity-50">
            {deleting ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />} {t('modal.delete')}
          </button>}
          <div className="flex items-center gap-2 flex-1 justify-end">
            {msg && <span className={`text-sm font-medium ${/Failed$/.test(msg) ? 'text-red-600' : 'text-green-600'}`}>{t(`modal.msg.${msg}`)}</span>}
            <button onClick={sharePlan} disabled={sharing} data-tid="plan.share"
              title={t('modal.shareTitle')}
              className="flex items-center gap-1.5 px-3 py-2 text-violet-700 border border-violet-300 rounded-lg text-sm font-medium hover:bg-violet-50 transition-colors disabled:opacity-50">
              {sharing ? <Loader2 size={14} className="animate-spin" /> : <Share2 size={14} />} {t('modal.share')}
            </button>
            {!inline && <button onClick={onClose} data-tid="plan.modal-close" className="px-4 py-2 text-gray-600 border border-gray-300 rounded-lg text-sm font-medium hover:bg-gray-100 transition-colors">
              {t('modal.close')}
            </button>}
            <button onClick={save} disabled={saving} data-tid="plan.save"
              className="flex items-center gap-1.5 px-4 py-2 bg-teal-700 text-white rounded-lg text-sm font-semibold hover:bg-teal-800 disabled:opacity-50 transition-all">
              {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />} {t('modal.save')}
            </button>
          </div>
        </div>
      </>
  )

  if (inline) {
    return (
      <div data-tid="plan.inline" className="bg-white rounded-2xl shadow-sm border border-gray-100 flex flex-col overflow-hidden">
        {card}
      </div>
    )
  }

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center sm:p-4">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={onClose} />

      {/* Modal — full-height bottom sheet on mobile, centered card on sm+ */}
      <div className="relative bg-white rounded-t-2xl sm:rounded-2xl shadow-2xl w-full sm:max-w-2xl h-[92vh] sm:h-auto sm:max-h-[90vh] flex flex-col overflow-hidden">
        {card}
      </div>
    </div>
  )
}
