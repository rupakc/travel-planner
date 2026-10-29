import { useState, useEffect, useRef } from 'react'
import { useLocation } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { useSearchData } from '../context/SearchDataContext'
import { track } from '../utils/analytics'
import { Calendar, Users, DollarSign, Globe, Search, Plane, MapPin, Plus, X } from 'lucide-react'
import AirportSearch from '../components/ui/AirportSearch'
import NationalitySearch from '../components/ui/NationalitySearch'
import TagInput from '../components/ui/TagInput'
import TravelerPanel from '../components/ui/TravelerPanel'
import RecentSearches from '../components/RecentSearches'
import OnboardingTour from '../components/OnboardingTour'
import useFirstRunTour from '../hooks/useFirstRunTour'
import { discoverDestinations, compareDestination, getRecentSearches, saveRecentSearch, deleteRecentSearch } from '../services/api'
import CompareTable from '../components/CompareTable'
import { buildCompareRequests } from '../utils/compare'
import { toRecentSearch, recentSearchToForm, describeRecentSearch } from '../utils/recentSearches'

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

// First-run tour of the Search page, in page order (the nav is sticky, so
// its step never scrolls). Steps whose element isn't on screen — no recent
// searches yet, or the nav collapsed on a phone — are skipped.
const SEARCH_TOUR_STEPS = [
  { id: 'recent', target: '[data-tour="recent-searches"]', title: 'Pick up where you left off',
    body: 'Your recent searches live here. Load one to tweak it, or run it again as it was.' },
  { id: 'route', target: '[data-tour="route"]', title: 'Where are you headed?',
    body: 'Enter where you\'re flying from and to. Add stops on the way for a multi-city trip.' },
  { id: 'interests', target: '[data-tour="interests"]', title: 'Tell us what you love',
    body: 'Your interests and the discovery dial shape every recommendation — from famous classics to hidden gems.' },
  { id: 'preferences', target: '[data-tour="nav-preferences"]', title: 'We remember your details',
    body: 'Nationality, visas, travelers and interests you use here are saved to Preferences, and they pre-fill this form next time.' },
  { id: 'plan', target: '[data-tour="plan-button"]', title: 'Watch your trip come together',
    body: 'Flights, hotels, visa, weather and more stream in section by section — the first results appear within seconds.' },
  { id: 'my-plan', target: null, title: 'Build your plan',
    body: 'Add the flights, hotels and activities you like to My Plan, see where the money goes, then add it to your calendar or save it as a PDF. Chat is there for any question along the way.' },
]
// A short pause after the page is ready so preference pre-fill settles
const TOUR_START_DELAY_MS = 400

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
  const { preferences, updatePreferences, token, user } = useAuth()
  const { setPendingSearchData, hasSearchResults } = useSearchData()
  const location = useLocation()

  const today     = new Date().toISOString().split('T')[0]
  const nextWeek  = new Date(Date.now() + 7  * 86400000).toISOString().split('T')[0]
  const twoWeeks  = new Date(Date.now() + 14 * 86400000).toISOString().split('T')[0]

  const [mode, setMode] = useState('known')  // 'known' | 'discover' | 'compare'
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
    serendipity: 0.5,
  })
  // Multi-city: up to 3 additional cities after the primary destination
  // Intermediate stops on the way to the final destination (the To field).
  // Each: { city, nights } — nights optional; leftovers go to the final stop.
  const [extraStops, setExtraStops] = useState([])

  // Compare mode: shared trip fields + 2-3 destinations, one summary call each
  const [compareForm, setCompareForm] = useState(null)
  const [compareError, setCompareError] = useState(null)
  const [compareColumns, setCompareColumns] = useState(null)
  const compareRequests = useRef([])
  // Bumped on every run so responses from an older run are ignored
  const compareRun = useRef(0)

  const [recentSearches, setRecentSearches] = useState([])
  const [recentLoaded, setRecentLoaded] = useState(false)
  const [recentNotice, setRecentNotice] = useState(null)
  // While a loaded recent search is being edited it owns the form —
  // preferences arriving or re-syncing must not overwrite it. Cleared on submit.
  const loadedRecentRef = useRef(false)
  // Bumped by every list fetch and delete, so a slow fetch can't resurrect
  // a card the user has just removed
  const recentListSeq = useRef(0)

  const refreshRecentSearches = () => {
    if (!token) return
    const seq = ++recentListSeq.current
    getRecentSearches(token)
      .then(list => { if (seq === recentListSeq.current) setRecentSearches(list) })
      .catch(() => {})
      .finally(() => setRecentLoaded(true))
  }
  // SearchPage stays mounted behind the results, so refetch whenever it is
  // shown again — searches refined on the Results page are saved from there
  useEffect(() => { if (!hasSearchResults) refreshRecentSearches() }, [token, hasSearchResults])

  // First-run tour. SearchPage stays mounted behind Chat/Preferences and the
  // results, so it may only show while the Search form itself is on screen.
  // It opens by itself only for people new to the app — no search history —
  // and waits for that history to load so the page has stopped shifting.
  const tour = useFirstRunTour({
    username: user?.username,
    visible: location.pathname === '/' && !hasSearchResults && mode === 'known',
    eligible: recentLoaded && recentSearches.length === 0,
    delayMs: TOUR_START_DELAY_MS,
  })

  // Pre-fill from saved preferences
  useEffect(() => {
    if (!preferences || loadedRecentRef.current) return
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
    setCompareForm(c => c && ({
      ...c,
      nationality: preferences.nationality || c.nationality,
      residence_permits: preferences.residence_permits?.length ? preferences.residence_permits : c.residence_permits,
      existing_visas: preferences.existing_visas?.length ? preferences.existing_visas : c.existing_visas,
      interests: preferences.interests?.length ? preferences.interests : c.interests,
      budget_usd: preferences.budget_category ? (BUDGET_TO_USD[preferences.budget_category] || '') : c.budget_usd,
      adults: preferences.adults ?? c.adults,
      children: preferences.children ?? c.children,
      seniors: preferences.seniors ?? c.seniors,
      infants: preferences.infants ?? c.infants,
      accessibility_needs: preferences.accessibility_needs?.length ? preferences.accessibility_needs : c.accessibility_needs,
    }))
  }, [preferences])

  const toggleInterest = (id) =>
    setForm(f => ({ ...f, interests: f.interests.includes(id) ? f.interests.filter(i => i !== id) : [...f.interests, id] }))

  const startSearch = (form, extraStops) => {
    const totalTravelers = Math.max(1, form.adults + form.children + form.seniors + form.infants)
    const stops = extraStops
      .map(s => ({ city: (s.city || '').trim(), nights: s.nights }))
      .filter(s => s.city)
    const parseNights = (v) => {
      const n = parseInt(v, 10)
      return Number.isFinite(n) && n > 0 ? n : null
    }
    const searchData = {
      ...form,
      num_travelers: totalTravelers,
      budget_usd: form.budget_usd ? parseFloat(form.budget_usd) : null,
      // Journey order: stops along the way first, the To city (final
      // destination) last
      destinations: stops.length ? [...stops.map(s => s.city), form.destination] : null,
      destination_nights: stops.length ? [...stops.map(s => parseNights(s.nights)), null] : null,
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
    setRecentNotice(null)
    loadedRecentRef.current = false
    if (token) {
      saveRecentSearch(token, toRecentSearch(searchData))
        .then(refreshRecentSearches)
        .catch(err => console.warn('Could not save recent search', err))
    }
    setPendingSearchData(searchData)
  }

  const handleSubmit = (e) => {
    e.preventDefault()
    startSearch(form, extraStops)
  }

  const applyRecentSearch = (entry) => {
    const restored = recentSearchToForm(entry.search, today)
    loadedRecentRef.current = true
    setForm(f => ({ ...f, ...restored.form }))
    setExtraStops(restored.extraStops)
    return restored
  }

  const handleLoadRecent = (entry) => {
    const { datesShifted } = applyRecentSearch(entry)
    const { route } = describeRecentSearch(entry.search)
    setRecentNotice(datesShifted
      ? `Loaded ${route}. Its dates had passed, so they now start next week with the same trip length — check them, then plan.`
      : `Loaded ${route}. Change anything you like, then plan.`)
    track('recent_search_load', 'search', { dates_shifted: datesShifted })
  }

  const handleRerunRecent = (entry) => {
    const restored = applyRecentSearch(entry)
    track('recent_search_rerun', 'search', {})
    startSearch({ ...form, ...restored.form }, restored.extraStops)
  }

  const handleRemoveRecent = (entry) => {
    recentListSeq.current++
    setRecentSearches(list => list.filter(e => e.id !== entry.id))
    deleteRecentSearch(token, entry.id).catch(refreshRecentSearches)
  }

  // Entering Compare seeds it, once, from the known-destination form
  const openCompare = () => {
    setMode('compare')
    setCompareForm(c => c || {
      origin: form.origin, destinations: [form.destination, ''],
      departure_date: form.departure_date, return_date: form.return_date,
      nationality: form.nationality, residence_permits: form.residence_permits,
      existing_visas: form.existing_visas, interests: form.interests,
      budget_usd: form.budget_usd,
      adults: form.adults, children: form.children, seniors: form.seniors, infants: form.infants,
      accessibility_needs: form.accessibility_needs, serendipity: form.serendipity,
    })
  }

  const setCompareDestination = (i, v) =>
    setCompareForm(c => ({ ...c, destinations: c.destinations.map((d, j) => (j === i ? v : d)) }))

  const loadCompareColumn = async (index) => {
    const run = compareRun.current
    const request = compareRequests.current[index]
    const patch = (p) => setCompareColumns(cols => (cols ? cols.map((c, i) => (i === index ? { ...c, ...p } : c)) : cols))
    patch({ status: 'loading', error: null })
    try {
      const summary = await compareDestination(request, token)
      if (run === compareRun.current) patch({ status: 'done', summary })
    } catch (err) {
      if (run === compareRun.current) {
        patch({ status: 'error', error: err.response?.data?.detail || "Couldn't load this destination" })
      }
    }
  }

  const retryCompareColumn = (index) => {
    if (compareColumns?.[index]?.status === 'loading') return
    loadCompareColumn(index)
  }

  const handleCompare = (e) => {
    e.preventDefault()
    const requests = buildCompareRequests(compareForm)
    if (requests.length < 2) {
      setCompareError('Add at least two different destinations to compare.')
      return
    }
    setCompareError(null)
    compareRun.current++
    compareRequests.current = requests
    setCompareColumns(requests.map(r => ({ destination: r.destination, status: 'loading' })))
    track('compare_run', 'search', { count: requests.length })
    requests.forEach((_, i) => loadCompareColumn(i))
  }

  // Runs the compared request as a normal full search, through startSearch
  const handlePlanCompared = (index) => {
    const request = compareRequests.current[index]
    if (!request) return
    // Only the fields Compare shows come from the compared request; the rest
    // (permits, visas, accessibility, serendipity) stay as in the known form
    const { destination, origin, departure_date, return_date, nationality, interests,
      budget_usd, adults, children, seniors, infants } = request
    const planForm = { ...form, destination, origin, departure_date, return_date, nationality,
      interests, budget_usd, adults, children, seniors, infants }
    setForm(planForm)
    setExtraStops([])
    setMode('known')
    startSearch(planForm, [])
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
      <OnboardingTour open={tour.open} steps={SEARCH_TOUR_STEPS} onClose={tour.close} />

      {/* Hero */}
      <div className="max-w-4xl mx-auto px-4 pt-10 pb-6 text-center">
        <div className="inline-flex items-center gap-1.5 px-3 py-1 bg-teal-50 border border-teal-200 rounded-full text-teal-700 text-xs font-semibold mb-4">
          <Plane size={12} strokeWidth={2.5} />
          AI-Powered Travel Planning
        </div>
        <h1 className="font-display text-3xl sm:text-4xl md:text-5xl font-bold mb-3 tracking-tight leading-[1.1] bg-gradient-to-r from-teal-700 via-teal-600 to-sky-600 bg-clip-text text-transparent">Plan Your Perfect Trip</h1>
        <p className="text-slate-500 text-lg">Flights, hotels, activities, visa, SIM &amp; itinerary — all in one place.</p>
        <button type="button" onClick={() => { setMode('known'); tour.start() }}
          className="mt-2 text-sm font-medium text-teal-600 hover:text-teal-800 underline-offset-2 hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400 rounded">
          New here? Take a quick tour
        </button>
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
            <button type="button"
              onClick={openCompare}
              className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-all ${mode === 'compare' ? 'bg-white shadow text-gray-900' : 'text-gray-500 hover:text-gray-700'}`}>
              Compare ⚖️
            </button>
          </div>

          {mode === 'known' && (
            <RecentSearches entries={recentSearches} today={today}
              onLoad={handleLoadRecent} onRerun={handleRerunRecent} onRemove={handleRemoveRecent} />
          )}

          {mode === 'known' && <form onSubmit={handleSubmit} className="space-y-6">

            {recentNotice && (
              <div role="status" className="flex items-start gap-2 px-3 py-2 bg-teal-50 border border-teal-200 rounded-lg text-sm text-teal-800">
                <span className="flex-1">{recentNotice}</span>
                <button type="button" onClick={() => setRecentNotice(null)} aria-label="Dismiss"
                  className="text-teal-500 hover:text-teal-700 shrink-0 mt-0.5"><X size={14} /></button>
              </div>
            )}

            {/* Origin + Destination */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4" data-tour="route">
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

            {/* Intermediate stops — visited on the way to the To city */}
            <div className="space-y-3">
              {extraStops.map((stop, i) => (
                <div key={i} className="flex items-end gap-2">
                  <div className="flex-1">
                    <AirportSearch
                      label={<span className="inline-flex items-center gap-1.5"><MapPin size={13} /> Stop {i + 1} — on the way</span>}
                      value={stop.city}
                      onChange={v => setExtraStops(stops => stops.map((s, j) => (j === i ? { ...s, city: v } : s)))}
                      placeholder="Stopover city…"
                      required
                    />
                  </div>
                  <div className="w-24">
                    <label className="block text-xs font-medium text-gray-500 mb-1">Nights <span className="text-gray-300">(opt)</span></label>
                    <input type="number" min="1" max="30" value={stop.nights}
                      onChange={e => setExtraStops(stops => stops.map((s, j) => (j === i ? { ...s, nights: e.target.value } : s)))}
                      placeholder="auto"
                      className="w-full px-2.5 py-2.5 border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-teal-400 text-sm" />
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
                  onClick={() => setExtraStops(stops => [...stops, { city: '', nights: '' }])}
                  className="inline-flex items-center gap-1.5 text-sm font-medium text-teal-600 hover:text-teal-800 transition-colors">
                  <Plus size={14} /> Add a stop on the way (multi-city)
                </button>
              )}
              {extraStops.length > 0 && (
                <p className="text-xs text-gray-400">
                  Your route: {form.origin ? form.origin.split(',')[0] : 'Origin'} → {extraStops.filter(s => (s.city || '').trim()).map(s => s.city.split(',')[0]).join(' → ') || 'stops'} → <span className="font-medium text-gray-500">{form.destination ? form.destination.split(',')[0] : 'your destination'}</span>.
                  Stops are visited on the way; the "To" city is your final destination. Nights left blank are split automatically.
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
            <div data-tour="interests">
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

            {/* Serendipity dial */}
            <div>
              <div className="flex items-center justify-between mb-1">
                <label className={labelClass}>🎯 Discovery style</label>
                <span className="text-xs font-semibold text-teal-600">
                  {form.serendipity < 0.33 ? '🏛️ Famous classics' : form.serendipity > 0.66 ? '💎 Hidden gems' : '⚖️ Balanced mix'}
                </span>
              </div>
              <input
                type="range" min="0" max="1" step="0.05"
                value={form.serendipity}
                onChange={e => setForm(f => ({ ...f, serendipity: parseFloat(e.target.value) }))}
                className="w-full accent-teal-600 cursor-pointer"
                aria-label="Serendipity dial: classics to hidden gems"
              />
              <div className="flex justify-between text-[11px] text-gray-400 mt-0.5">
                <span>Iconic must-sees</span>
                <span>Off the beaten path</span>
              </div>
            </div>

            <button type="submit" data-tour="plan-button"
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

          {mode === 'compare' && compareForm && (
            <div className="space-y-6">
              <form onSubmit={handleCompare} className="space-y-6">
                <p className="text-sm text-gray-500 text-center">Compare two or three destinations side by side — cost, flights, hotels, weather and visa — before you commit to a full plan.</p>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <AirportSearch
                    label={<span className="inline-flex items-center gap-1.5"><Plane size={13} /> From</span>}
                    value={compareForm.origin}
                    onChange={v => setCompareForm(c => ({ ...c, origin: v }))}
                    placeholder="City or airport…"
                    required
                  />
                </div>

                <div className="space-y-3">
                  {compareForm.destinations.map((dest, i) => (
                    <div key={i} className="flex items-end gap-2">
                      <div className="flex-1">
                        <AirportSearch
                          label={<span className="inline-flex items-center gap-1.5"><MapPin size={13} /> Destination {i + 1}</span>}
                          value={dest}
                          onChange={v => setCompareDestination(i, v)}
                          placeholder="City or airport…"
                        />
                      </div>
                      {compareForm.destinations.length > 2 && (
                        <button type="button" title="Remove this destination" aria-label={`Remove destination ${i + 1}`}
                          onClick={() => setCompareForm(c => ({ ...c, destinations: c.destinations.filter((_, j) => j !== i) }))}
                          className="mb-1 p-2.5 rounded-lg border border-gray-200 text-gray-400 hover:text-red-500 hover:border-red-200 transition-colors">
                          <X size={14} />
                        </button>
                      )}
                    </div>
                  ))}
                  {compareForm.destinations.length < 3 && (
                    <button type="button"
                      onClick={() => setCompareForm(c => ({ ...c, destinations: [...c.destinations, ''] }))}
                      className="inline-flex items-center gap-1.5 text-sm font-medium text-teal-600 hover:text-teal-800 transition-colors">
                      <Plus size={14} /> Add another
                    </button>
                  )}
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div>
                    <label className={labelClass}><span className="inline-flex items-center gap-1.5"><Calendar size={13} /> Departure</span></label>
                    <input type="date" required value={compareForm.departure_date} min={today}
                      onChange={e => setCompareForm(c => ({ ...c, departure_date: e.target.value }))} className={inputClass} />
                  </div>
                  <div>
                    <label className={labelClass}><span className="inline-flex items-center gap-1.5"><Calendar size={13} /> Return</span></label>
                    <input type="date" value={compareForm.return_date} min={compareForm.departure_date}
                      onChange={e => setCompareForm(c => ({ ...c, return_date: e.target.value }))} className={inputClass} />
                  </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-3 gap-4 items-start">
                  <NationalitySearch
                    label={<span className="inline-flex items-center gap-1.5"><Globe size={13} /> Nationality</span>}
                    value={compareForm.nationality}
                    onChange={v => setCompareForm(c => ({ ...c, nationality: v }))}
                    placeholder="American, Indian…"
                    required
                  />
                  <div>
                    <label className={labelClass}><span className="inline-flex items-center gap-1.5"><DollarSign size={13} /> Budget (USD)</span></label>
                    <input type="number" value={compareForm.budget_usd} min="0" step="100"
                      onChange={e => setCompareForm(c => ({ ...c, budget_usd: e.target.value }))}
                      placeholder="Optional" className={inputClass} />
                  </div>
                  <div>
                    <label className={labelClass}><span className="inline-flex items-center gap-1.5"><Users size={13} /> Travelers</span></label>
                    <TravelerPanel form={compareForm} setForm={setCompareForm} />
                  </div>
                </div>

                <div>
                  <label className={labelClass}>✨ Interests</label>
                  <div className="flex flex-wrap gap-2 mt-1">
                    {INTERESTS.map(({ id, label }) => (
                      <button key={id} type="button"
                        onClick={() => setCompareForm(c => ({ ...c, interests: c.interests.includes(id) ? c.interests.filter(i => i !== id) : [...c.interests, id] }))}
                        className={`px-3 py-1.5 rounded-full text-sm font-medium border-2 transition-all ${compareForm.interests.includes(id) ? 'bg-teal-600 border-teal-600 text-white shadow-sm ring-2 ring-teal-200 ring-offset-1' : 'bg-white border-gray-200 text-gray-600 hover:border-teal-300 hover:text-teal-600'}`}>
                        {label}
                      </button>
                    ))}
                  </div>
                </div>

                {compareError && <p role="alert" className="text-center text-red-500 text-sm">{compareError}</p>}

                <button type="submit"
                  className="w-full flex items-center justify-center gap-2 py-3.5 px-6 bg-gradient-to-r from-teal-600 to-teal-700 hover:from-teal-700 hover:to-teal-800 text-white font-semibold rounded-xl shadow-lg hover:shadow-xl active:scale-[0.99] transition-all text-base">
                  <Search size={18} /> Compare destinations
                </button>
              </form>

              {compareColumns && (
                <CompareTable columns={compareColumns} onPlan={handlePlanCompared} onRetry={retryCompareColumn} />
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
