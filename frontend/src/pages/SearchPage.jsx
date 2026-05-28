import { useState, useEffect, useRef } from 'react'
import { useAuth } from '../context/AuthContext'
import { useSearchData } from '../context/SearchDataContext'
import { track } from '../utils/analytics'
import { Calendar, Users, DollarSign, Globe, Search, Plane, MapPin, ChevronDown, ChevronUp, Plus, Minus } from 'lucide-react'
import AirportSearch from '../components/ui/AirportSearch'
import NationalitySearch from '../components/ui/NationalitySearch'
import TagInput from '../components/ui/TagInput'

const ACCESSIBILITY_OPTIONS = [
  { id: 'wheelchair',           label: '♿ Wheelchair / Mobility aid' },
  { id: 'visual_impairment',    label: '👁️ Visual impairment' },
  { id: 'hearing_impairment',   label: '🦻 Hearing impairment' },
  { id: 'cognitive_disability', label: '🧠 Cognitive / Neurodivergent' },
]

const ACCESS_EMOJI = {
  wheelchair:           '♿',
  visual_impairment:    '👁️',
  hearing_impairment:   '🦻',
  cognitive_disability: '🧠',
}

function TravelerPanel({ form, setForm }) {
  const [open, setOpen] = useState(false)
  const panelRef = useRef(null)

  useEffect(() => {
    if (!open) return
    const handler = (e) => {
      if (panelRef.current && !panelRef.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  const counts = [
    { key: 'adults',   label: 'Adults',   sub: '18–64' },
    { key: 'seniors',  label: 'Seniors',  sub: '65+' },
    { key: 'children', label: 'Children', sub: '5–17' },
    { key: 'infants',  label: 'Infants',  sub: '0–4' },
  ]

  const total = form.adults + form.seniors + form.children + form.infants
  const chips = []
  if (form.adults)   chips.push(`${form.adults}👤`)
  if (form.seniors)  chips.push(`${form.seniors}🧓`)
  if (form.children) chips.push(`${form.children}🧒`)
  if (form.infants)  chips.push(`${form.infants}👶`)
  const accessEmojis = form.accessibility_needs.map(id => ACCESS_EMOJI[id] || '').filter(Boolean)

  const change = (key, delta) => {
    setForm(f => {
      const next = Math.max(0, (f[key] || 0) + delta)
      const newTotal = (key === 'adults' ? next : f.adults) + (key === 'seniors' ? next : f.seniors) + (key === 'children' ? next : f.children) + (key === 'infants' ? next : f.infants)
      if (newTotal < 1) return f
      return { ...f, [key]: next }
    })
  }

  const toggleAccess = (id) => {
    setForm(f => ({
      ...f,
      accessibility_needs: f.accessibility_needs.includes(id)
        ? f.accessibility_needs.filter(x => x !== id)
        : [...f.accessibility_needs, id],
    }))
  }

  return (
    <div className="relative" ref={panelRef}>
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-3 py-2.5 border border-gray-200 rounded-lg bg-white hover:bg-gray-50 transition-colors"
      >
        <div className="flex items-center gap-1.5 min-w-0 flex-1 overflow-hidden">
          <Users size={13} className="text-gray-500 shrink-0" />
          <span className="text-sm text-gray-700 whitespace-nowrap">
            {chips.length ? chips.join(' ') : `${total} traveler${total !== 1 ? 's' : ''}`}
            {accessEmojis.length > 0 && <span className="text-teal-600"> {accessEmojis.join('')}</span>}
          </span>
        </div>
        {open ? <ChevronUp size={14} className="text-gray-400 shrink-0" /> : <ChevronDown size={14} className="text-gray-400 shrink-0" />}
      </button>

      {open && (
        <div className="absolute top-full left-0 right-0 z-50 mt-1 bg-white border border-gray-200 rounded-lg shadow-xl px-3 py-3 space-y-3">
          {counts.map(({ key, label, sub }) => (
            <div key={key} className="flex items-center justify-between">
              <div>
                <span className="text-sm font-medium text-gray-700">{label}</span>
                <span className="text-xs text-gray-400 ml-1">({sub})</span>
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => change(key, -1)}
                  disabled={form[key] === 0 || (key === 'adults' && total <= 1 && form[key] <= 1)}
                  className="w-7 h-7 flex items-center justify-center rounded-full border border-gray-200 bg-gray-50 hover:bg-gray-100 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                >
                  <Minus size={12} />
                </button>
                <span className="w-5 text-center text-sm font-semibold text-gray-800">{form[key] || 0}</span>
                <button
                  type="button"
                  onClick={() => change(key, 1)}
                  className="w-7 h-7 flex items-center justify-center rounded-full border border-teal-200 bg-teal-50 hover:bg-teal-100 transition-colors text-teal-700"
                >
                  <Plus size={12} />
                </button>
              </div>
            </div>
          ))}

          <div className="pt-2 border-t border-gray-100">
            <p className="text-xs font-medium text-gray-600 mb-2">Accessibility needs</p>
            <div className="space-y-1.5">
              {ACCESSIBILITY_OPTIONS.map(({ id, label }) => (
                <label key={id} className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={form.accessibility_needs.includes(id)}
                    onChange={() => toggleAccess(id)}
                    className="w-4 h-4 rounded border-gray-300 text-teal-600 focus:ring-teal-400"
                  />
                  <span className="text-sm text-gray-700">{label}</span>
                </label>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

const INTERESTS = [
  { id: 'food',      label: '🍜 Food' },
  { id: 'history',   label: '🏛️ History' },
  { id: 'adventure', label: '🧗 Adventure' },
  { id: 'culture',   label: '🎭 Culture' },
  { id: 'nature',    label: '🌿 Nature' },
  { id: 'shopping',  label: '🛍️ Shopping' },
  { id: 'nightlife', label: '🌙 Nightlife' },
  { id: 'wellness',  label: '🧘 Wellness' },
  { id: 'art',       label: '🎨 Art' },
  { id: 'family',    label: '👨‍👩‍👧 Family' },
]

const BUDGET_TO_USD = { low: 1000, medium: 3000, high: 8000 }
const USD_TO_BUDGET = (usd) => {
  if (!usd) return 'medium'
  const n = parseFloat(usd)
  if (n <= 1500) return 'low'
  if (n <= 5000) return 'medium'
  return 'high'
}

export default function SearchPage() {
  const { preferences, updatePreferences } = useAuth()
  const { setPendingSearchData } = useSearchData()

  const today     = new Date().toISOString().split('T')[0]
  const nextWeek  = new Date(Date.now() + 7  * 86400000).toISOString().split('T')[0]
  const twoWeeks  = new Date(Date.now() + 14 * 86400000).toISOString().split('T')[0]

  const [form, setForm] = useState({
    origin: '', destination: '',
    departure_date: nextWeek, return_date: twoWeeks,
    nationality: '', residence_permits: [], existing_visas: [],
    interests: [], budget_usd: '',
    num_travelers: 1,
    adults: 1, children: 0, seniors: 0, infants: 0,
    accessibility_needs: [],
  })

  // Pre-fill from saved preferences
  useEffect(() => {
    if (!preferences) return
    setForm(f => ({
      ...f,
      nationality: preferences.nationality || f.nationality,
      residence_permits: preferences.residence_permits?.length ? preferences.residence_permits : f.residence_permits,
      existing_visas: preferences.existing_visas?.length ? preferences.existing_visas : f.existing_visas,
      interests: preferences.interests?.length ? preferences.interests : f.interests,
      num_travelers: preferences.num_travelers || f.num_travelers,
      budget_usd: preferences.budget_category ? (BUDGET_TO_USD[preferences.budget_category] || '') : f.budget_usd,
      adults: preferences.adults ?? f.adults,
      children: preferences.children ?? f.children,
      seniors: preferences.seniors ?? f.seniors,
      infants: preferences.infants ?? f.infants,
      accessibility_needs: preferences.accessibility_needs?.length ? preferences.accessibility_needs : f.accessibility_needs,
    }))
  }, [preferences])

  const toggleInterest = (id) =>
    setForm(f => ({ ...f, interests: f.interests.includes(id) ? f.interests.filter(i => i !== id) : [...f.interests, id] }))

  const handleSubmit = (e) => {
    e.preventDefault()
    const totalTravelers = Math.max(1, form.adults + form.children + form.seniors + form.infants)
    const searchData = {
      ...form,
      num_travelers: totalTravelers,
      budget_usd: form.budget_usd ? parseFloat(form.budget_usd) : null,
    }

    // Two-way binding: sync search values back to preferences
    updatePreferences({
      nationality: form.nationality,
      current_residence: preferences?.current_residence || '',
      residence_permits: form.residence_permits,
      existing_visas: form.existing_visas,
      interests: form.interests,
      num_travelers: totalTravelers,
      budget_category: USD_TO_BUDGET(form.budget_usd),
      adults: form.adults,
      children: form.children,
      seniors: form.seniors,
      infants: form.infants,
      accessibility_needs: form.accessibility_needs,
    })

    track('search_submit', 'search', {
      destination: form.destination,
      num_interests: form.interests.length,
      num_travelers: totalTravelers,
    })
    setPendingSearchData(searchData)
  }

  const inputClass = "w-full px-3 py-2.5 border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-teal-400 focus:border-teal-400 transition-colors text-sm bg-white"
  const labelClass = "block text-sm font-medium text-gray-700 mb-1"

  return (
    <div>
      {/* Hero */}
      <div className="max-w-4xl mx-auto px-4 pt-10 pb-6 text-center">
        <div className="inline-flex items-center gap-1.5 px-3 py-1 bg-teal-50 border border-teal-200 rounded-full text-teal-700 text-xs font-semibold mb-4">
          <Plane size={12} strokeWidth={2.5} />
          AI-Powered Travel Planning
        </div>
        <h1 className="font-display text-3xl sm:text-4xl md:text-5xl font-bold mb-3 tracking-tight leading-[1.1] bg-gradient-to-r from-teal-700 via-teal-600 to-sky-600 bg-clip-text text-transparent">Plan Your Perfect Trip</h1>
        <p className="text-slate-500 text-lg">Flights, hotels, activities, visa, SIM &amp; itinerary — all in one place.</p>
      </div>

      {/* Form card */}
      <div className="max-w-4xl mx-auto px-4 pb-16 -mt-2">
        <div className="bg-white rounded-3xl shadow-2xl ring-1 ring-gray-100 p-4 sm:p-6 md:p-8">
          <form onSubmit={handleSubmit} className="space-y-6">

            {/* Origin + Destination */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <AirportSearch
                label={<span className="inline-flex items-center gap-1.5"><Plane size={13} /> From</span>}
                value={form.origin}
                onChange={v => setForm(f => ({ ...f, origin: v }))}
                placeholder="City or airport…"
                required
              />
              <AirportSearch
                label={<span className="inline-flex items-center gap-1.5"><MapPin size={13} /> To</span>}
                value={form.destination}
                onChange={v => setForm(f => ({ ...f, destination: v }))}
                placeholder="City or airport…"
                required
              />
            </div>

            {/* Dates */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label className={labelClass}><span className="inline-flex items-center gap-1.5"><Calendar size={13} /> Departure</span></label>
                <input type="date" required value={form.departure_date} min={today}
                  onChange={e => setForm(f => ({ ...f, departure_date: e.target.value }))} className={inputClass} />
              </div>
              <div>
                <label className={labelClass}><span className="inline-flex items-center gap-1.5"><Calendar size={13} /> Return</span></label>
                <input type="date" value={form.return_date} min={form.departure_date}
                  onChange={e => setForm(f => ({ ...f, return_date: e.target.value }))} className={inputClass} />
              </div>
            </div>

            {/* Nationality + Budget + Travelers */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 items-start">
              <NationalitySearch
                label={<span className="inline-flex items-center gap-1.5"><Globe size={13} /> Nationality</span>}
                value={form.nationality}
                onChange={v => setForm(f => ({ ...f, nationality: v }))}
                placeholder="American, Indian…"
                required
              />
              <div>
                <label className={labelClass}><span className="inline-flex items-center gap-1.5"><DollarSign size={13} /> Budget (USD)</span></label>
                <input type="number" value={form.budget_usd} min="0" step="100"
                  onChange={e => setForm(f => ({ ...f, budget_usd: e.target.value }))}
                  placeholder="Optional" className={inputClass} />
              </div>
              <div>
                <label className={labelClass}><span className="inline-flex items-center gap-1.5"><Users size={13} /> Travelers</span></label>
                <TravelerPanel form={form} setForm={setForm} />
              </div>
            </div>

            {/* Permits & Visas */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <TagInput label="🏠 Residence Permits (if any)" value={form.residence_permits}
                onChange={v => setForm(f => ({ ...f, residence_permits: v }))} placeholder="Schengen, UK, UAE…" />
              <TagInput label="📋 Existing Visas (if any)" value={form.existing_visas}
                onChange={v => setForm(f => ({ ...f, existing_visas: v }))} placeholder="US, Japan, Canada…" />
            </div>

            {/* Interests */}
            <div>
              <label className={labelClass}>✨ Interests</label>
              <div className="flex flex-wrap gap-2 mt-1">
                {INTERESTS.map(({ id, label }) => (
                  <button key={id} type="button" onClick={() => toggleInterest(id)}
                    className={`px-3 py-1.5 rounded-full text-sm font-medium border-2 transition-all ${form.interests.includes(id) ? 'bg-teal-600 border-teal-600 text-white shadow-sm ring-2 ring-teal-200 ring-offset-1' : 'bg-white border-gray-200 text-gray-600 hover:border-teal-300 hover:text-teal-600'}`}>
                    {label}
                  </button>
                ))}
              </div>
            </div>

            <button type="submit"
              className="w-full flex items-center justify-center gap-2 py-3.5 px-6 bg-gradient-to-r from-teal-600 to-teal-700 hover:from-teal-700 hover:to-teal-800 text-white font-semibold rounded-xl shadow-lg hover:shadow-xl active:scale-[0.99] transition-all text-base">
              <Search size={18} /> Plan My Trip
            </button>
          </form>
        </div>
      </div>
    </div>
  )
}
