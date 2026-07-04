import { useState, useEffect, useRef } from 'react'
import { useAuth } from '../context/AuthContext'
import { useSearchData } from '../context/SearchDataContext'
import { track } from '../utils/analytics'
import { Calendar, Users, DollarSign, Globe, Search, Plane, MapPin, Plus, X } from 'lucide-react'
import AirportSearch from '../components/ui/AirportSearch'
import NationalitySearch from '../components/ui/NationalitySearch'
import TagInput from '../components/ui/TagInput'
import TravelerPanel from '../components/ui/TravelerPanel'
import { discoverDestinations } from '../services/api'

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

function DestinationCard({ dest, onSelect }) {
  return (
    <div className="bg-white border border-gray-200 rounded-2xl p-4 shadow-sm hover:shadow-md transition-shadow flex flex-col gap-3">
      <div className="flex items-start justify-between gap-2">
        <div>
          <h4 className="font-semibold text-gray-900">{dest.city}</h4>
          <p className="text-xs text-gray-500">{dest.country}</p>
        </div>
        <span className="text-2xl">{dest.weather_emoji || '🌍'}</span>
      </div>

      {/* Visa badge */}
      <span className={`self-start text-xs px-2 py-0.5 rounded-full font-medium ${
        dest.visa_type === 'visa-free' ? 'bg-green-100 text-green-700' :
        dest.visa_type === 'visa-on-arrival' ? 'bg-blue-100 text-blue-700' :
        dest.visa_type === 'e-visa' ? 'bg-sky-100 text-sky-700' :
        dest.visa_type === 'required' ? 'bg-orange-100 text-orange-700' :
        'bg-amber-100 text-amber-700'
      }`}>
        {dest.visa_verified ? '' : '⚠️ '}{dest.visa_type === 'visa-free' ? '✓ Visa-free' : dest.visa_type === 'visa-on-arrival' ? 'Visa on arrival' : dest.visa_type === 'e-visa' ? 'e-Visa' : dest.visa_type === 'required' ? 'Visa required' : 'Verify visa'}
      </span>

      {/* Weather */}
      <p className="text-xs text-gray-600">{dest.weather_description}</p>

      {/* Flight duration */}
      {dest.flight_duration_label && (
        <p className="text-xs text-gray-500 flex items-center gap-1"><Plane size={11} />{dest.flight_duration_label}</p>
      )}

      {/* Cost estimate */}
      {dest.estimated_cost_usd_low && (
        <p className="text-sm font-medium text-teal-700">
          ~${dest.estimated_cost_usd_low.toLocaleString()}–${dest.estimated_cost_usd_high.toLocaleString()} <span className="text-xs font-normal text-gray-500">rough estimate</span>
        </p>
      )}

      {/* Match reasons */}
      {dest.match_reasons?.length > 0 && (
        <ul className="space-y-1">
          {dest.match_reasons.slice(0, 2).map((r, i) => (
            <li key={i} className="text-xs text-gray-600 flex gap-1.5"><span className="text-teal-500 mt-0.5">✓</span><span>{r}</span></li>
          ))}
        </ul>
      )}

      <button type="button" onClick={onSelect}
        className="mt-auto w-full py-2 px-3 bg-teal-600 hover:bg-teal-700 text-white text-sm font-medium rounded-lg transition-colors">
        Plan this trip →
      </button>
    </div>
  )
}

export default function SearchPage() {
  const { preferences, updatePreferences } = useAuth()
  const { setPendingSearchData } = useSearchData()

  const today     = new Date().toISOString().split('T')[0]
  const nextWeek  = new Date(Date.now() + 7  * 86400000).toISOString().split('T')[0]
  const twoWeeks  = new Date(Date.now() + 14 * 86400000).toISOString().split('T')[0]

  const [mode, setMode] = useState('known')  // 'known' | 'discover'
  const [discoverForm, setDiscoverForm] = useState({
    origin: '',
    nationality: '',
    departure_date: nextWeek,
    return_date: twoWeeks,
    budget_usd: '',
    interests: [],
    adults: 1, children: 0, seniors: 0, infants: 0,
  })
  const [discovering, setDiscovering] = useState(false)
  const [destinations, setDestinations] = useState(null)
  const [discoverError, setDiscoverError] = useState(null)

  const [form, setForm] = useState({
    origin: '', destination: '',
    departure_date: nextWeek, return_date: twoWeeks,
    nationality: '', residence_permits: [], existing_visas: [],
    interests: [], budget_usd: '',
    num_travelers: 1,
    adults: 1, children: 0, seniors: 0, infants: 0,
    accessibility_needs: [],
  })
  // Multi-city: up to 3 additional cities after the primary destination
  const [extraStops, setExtraStops] = useState([])

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
    setDiscoverForm(f => ({
      ...f,
      nationality: preferences.nationality || f.nationality,
      interests: preferences.interests?.length ? preferences.interests : f.interests,
      adults: preferences.adults ?? f.adults,
      children: preferences.children ?? f.children,
      seniors: preferences.seniors ?? f.seniors,
      infants: preferences.infants ?? f.infants,
    }))
  }, [preferences])

  const toggleInterest = (id) =>
    setForm(f => ({ ...f, interests: f.interests.includes(id) ? f.interests.filter(i => i !== id) : [...f.interests, id] }))

  const handleSubmit = (e) => {
    e.preventDefault()
    const totalTravelers = Math.max(1, form.adults + form.children + form.seniors + form.infants)
    const stops = extraStops.map(s => s.trim()).filter(Boolean)
    const searchData = {
      ...form,
      num_travelers: totalTravelers,
      budget_usd: form.budget_usd ? parseFloat(form.budget_usd) : null,
      destinations: stops.length ? [form.destination, ...stops] : null,
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
      num_cities: 1 + stops.length,
    })
    setPendingSearchData(searchData)
  }

  const handleDiscover = async () => {
    setDiscovering(true)
    setDiscoverError(null)
    setDestinations(null)
    try {
      const totalTravelers = Math.max(1, discoverForm.adults + discoverForm.children + discoverForm.seniors + discoverForm.infants)
      const result = await discoverDestinations({
        origin: discoverForm.origin,
        nationality: discoverForm.nationality,
        departure_date: discoverForm.departure_date,
        return_date: discoverForm.return_date || null,
        budget_usd: discoverForm.budget_usd ? parseFloat(discoverForm.budget_usd) : null,
        interests: discoverForm.interests,
        adults: discoverForm.adults,
        children: discoverForm.children,
        seniors: discoverForm.seniors,
        infants: discoverForm.infants,
      })
      setDestinations(result.destinations || [])
    } catch (err) {
      setDiscoverError(err.response?.data?.detail || 'Discovery failed — please try again')
    } finally {
      setDiscovering(false)
    }
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
          {/* Mode toggle */}
          <div className="flex items-center gap-2 mb-6 p-1 bg-gray-100 rounded-xl w-fit mx-auto">
            <button type="button"
              onClick={() => setMode('known')}
              className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-all ${mode === 'known' ? 'bg-white shadow text-gray-900' : 'text-gray-500 hover:text-gray-700'}`}>
              I know where I'm going
            </button>
            <button type="button"
              onClick={() => setMode('discover')}
              className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-all ${mode === 'discover' ? 'bg-white shadow text-gray-900' : 'text-gray-500 hover:text-gray-700'}`}>
              Surprise me 🎲
            </button>
          </div>

          {mode === 'known' && <form onSubmit={handleSubmit} className="space-y-6">

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

            {/* Multi-city stops */}
            <div className="space-y-3">
              {extraStops.map((stop, i) => (
                <div key={i} className="flex items-end gap-2">
                  <div className="flex-1">
                    <AirportSearch
                      label={<span className="inline-flex items-center gap-1.5"><MapPin size={13} /> Stop {i + 2}</span>}
                      value={stop}
                      onChange={v => setExtraStops(stops => stops.map((s, j) => (j === i ? v : s)))}
                      placeholder="Next city…"
                      required
                    />
                  </div>
                  <button type="button" title="Remove this stop"
                    onClick={() => setExtraStops(stops => stops.filter((_, j) => j !== i))}
                    className="mb-1 p-2.5 rounded-lg border border-gray-200 text-gray-400 hover:text-red-500 hover:border-red-200 transition-colors">
                    <X size={14} />
                  </button>
                </div>
              ))}
              {extraStops.length < 3 && (
                <button type="button"
                  onClick={() => setExtraStops(stops => [...stops, ''])}
                  className="inline-flex items-center gap-1.5 text-sm font-medium text-teal-600 hover:text-teal-800 transition-colors">
                  <Plus size={14} /> Add a stop (multi-city)
                </button>
              )}
              {extraStops.length > 0 && (
                <p className="text-xs text-gray-400">
                  We'll optimise the city order, split nights between cities and plan inter-city travel automatically.
                </p>
              )}
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
          </form>}

          {mode === 'discover' && (
            <div className="space-y-6">
              {/* Origin + Dates row */}
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <AirportSearch
                  label={<span className="inline-flex items-center gap-1.5"><Plane size={13} /> Flying from</span>}
                  value={discoverForm.origin}
                  onChange={v => setDiscoverForm(f => ({ ...f, origin: v }))}
                  placeholder="City or airport…"
                  required
                />
                <div>
                  <label className={labelClass}><span className="inline-flex items-center gap-1.5"><Calendar size={13} /> Departure</span></label>
                  <input type="date" required value={discoverForm.departure_date} min={today}
                    onChange={e => setDiscoverForm(f => ({ ...f, departure_date: e.target.value }))} className={inputClass} />
                </div>
                <div>
                  <label className={labelClass}><span className="inline-flex items-center gap-1.5"><Calendar size={13} /> Return</span></label>
                  <input type="date" value={discoverForm.return_date} min={discoverForm.departure_date}
                    onChange={e => setDiscoverForm(f => ({ ...f, return_date: e.target.value }))} className={inputClass} />
                </div>
              </div>

              {/* Nationality + Budget */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <NationalitySearch
                  label={<span className="inline-flex items-center gap-1.5"><Globe size={13} /> Nationality</span>}
                  value={discoverForm.nationality}
                  onChange={v => setDiscoverForm(f => ({ ...f, nationality: v }))}
                  placeholder="American, Indian…"
                  required
                />
                <div>
                  <label className={labelClass}><span className="inline-flex items-center gap-1.5"><DollarSign size={13} /> Budget (USD, optional)</span></label>
                  <input type="number" value={discoverForm.budget_usd} min="0" step="100"
                    onChange={e => setDiscoverForm(f => ({ ...f, budget_usd: e.target.value }))}
                    placeholder="Total trip budget" className={inputClass} />
                </div>
              </div>

              {/* Interests */}
              <div>
                <label className={labelClass}>✨ What are you into?</label>
                <div className="flex flex-wrap gap-2 mt-1">
                  {INTERESTS.map(({ id, label }) => (
                    <button key={id} type="button"
                      onClick={() => setDiscoverForm(f => ({ ...f, interests: f.interests.includes(id) ? f.interests.filter(i => i !== id) : [...f.interests, id] }))}
                      className={`px-3 py-1.5 rounded-full text-sm font-medium border-2 transition-all ${discoverForm.interests.includes(id) ? 'bg-teal-600 border-teal-600 text-white shadow-sm ring-2 ring-teal-200 ring-offset-1' : 'bg-white border-gray-200 text-gray-600 hover:border-teal-300 hover:text-teal-600'}`}>
                      {label}
                    </button>
                  ))}
                </div>
              </div>

              {/* Submit button */}
              <button type="button"
                disabled={discovering || !discoverForm.origin || !discoverForm.nationality}
                onClick={handleDiscover}
                className="w-full flex items-center justify-center gap-2 py-3.5 px-6 bg-gradient-to-r from-teal-600 to-teal-700 hover:from-teal-700 hover:to-teal-800 disabled:opacity-50 disabled:cursor-not-allowed text-white font-semibold rounded-xl shadow-lg hover:shadow-xl active:scale-[0.99] transition-all text-base">
                {discovering ? (
                  <><span className="animate-spin inline-block w-4 h-4 border-2 border-white border-t-transparent rounded-full" /> Finding destinations…</>
                ) : (
                  <><Search size={18} /> Find My Perfect Destination</>
                )}
              </button>

              {/* Error */}
              {discoverError && (
                <p className="text-center text-red-500 text-sm">{discoverError}</p>
              )}

              {/* Results: DestinationCard grid */}
              {destinations && destinations.length > 0 && (
                <div>
                  <h3 className="text-lg font-semibold text-gray-800 mb-3">Your personalized picks ✨</h3>
                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                    {destinations.map((dest, i) => (
                      <DestinationCard
                        key={i}
                        dest={dest}
                        onSelect={() => {
                          setForm(f => ({ ...f, destination: dest.city + ', ' + dest.country, origin: discoverForm.origin, departure_date: discoverForm.departure_date, return_date: discoverForm.return_date, nationality: discoverForm.nationality, budget_usd: discoverForm.budget_usd, interests: discoverForm.interests }))
                          setMode('known')
                          setDestinations(null)
                          window.scrollTo({ top: 0, behavior: 'smooth' })
                        }}
                      />
                    ))}
                  </div>
                </div>
              )}

              {destinations && destinations.length === 0 && (
                <p className="text-center text-gray-500 text-sm py-4">No destinations found — try different interests or a higher budget.</p>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
