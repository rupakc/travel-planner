import { useState, useEffect } from 'react'
import { useAuth } from '../context/AuthContext'
import { useSearchData } from '../context/SearchDataContext'
import { track } from '../utils/analytics'
import { Calendar, Users, DollarSign, Globe, Search, Plane, MapPin } from 'lucide-react'
import AirportSearch from '../components/ui/AirportSearch'
import NationalitySearch from '../components/ui/NationalitySearch'
import TagInput from '../components/ui/TagInput'

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
    interests: [], budget_usd: '', num_travelers: 1,
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
    }))
  }, [preferences])

  const toggleInterest = (id) =>
    setForm(f => ({ ...f, interests: f.interests.includes(id) ? f.interests.filter(i => i !== id) : [...f.interests, id] }))

  const handleSubmit = (e) => {
    e.preventDefault()
    const searchData = { ...form, budget_usd: form.budget_usd ? parseFloat(form.budget_usd) : null }

    // Two-way binding: sync search values back to preferences
    updatePreferences({
      nationality: form.nationality,
      current_residence: preferences?.current_residence || '',
      residence_permits: form.residence_permits,
      existing_visas: form.existing_visas,
      interests: form.interests,
      num_travelers: form.num_travelers,
      budget_category: USD_TO_BUDGET(form.budget_usd),
    })

    track('search_submit', 'search', {
      destination: form.destination,
      num_interests: form.interests.length,
      num_travelers: form.num_travelers,
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
                <div className="flex items-center border border-gray-200 rounded-lg overflow-hidden bg-white">
                  <button type="button" onClick={() => setForm(f => ({ ...f, num_travelers: Math.max(1, f.num_travelers - 1) }))}
                    className="px-3 py-2.5 bg-gray-50 hover:bg-gray-100 text-gray-600 font-bold text-lg leading-none">−</button>
                  <span className="flex-1 text-center text-sm font-medium py-2.5">{form.num_travelers}</span>
                  <button type="button" onClick={() => setForm(f => ({ ...f, num_travelers: Math.min(20, f.num_travelers + 1) }))}
                    className="px-3 py-2.5 bg-gray-50 hover:bg-gray-100 text-gray-600 font-bold text-lg leading-none">+</button>
                </div>
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
