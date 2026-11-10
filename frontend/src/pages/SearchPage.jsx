import { useState, useEffect, useRef, useMemo } from 'react'
import { useTranslation, Trans } from 'react-i18next'
import { useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { useSearchData } from '../context/SearchDataContext'
import { track } from '../utils/analytics'
import { Calendar, Users, DollarSign, Globe, Search, Plane, MapPin, Plus, X, Link2, ImagePlus } from 'lucide-react'
import ImportPanel from '../components/import/ImportPanel'
import ImportPreview from '../components/import/ImportPreview'
import { importLinkFromQuery } from '../utils/linkImport'
import usePageFileDrop from '../hooks/usePageFileDrop'
import AirportSearch from '../components/ui/AirportSearch'
import NationalitySearch from '../components/ui/NationalitySearch'
import TagInput from '../components/ui/TagInput'
import TravelerPanel from '../components/ui/TravelerPanel'
import RecentSearches from '../components/RecentSearches'
import OnboardingTour from '../components/OnboardingTour'
import useFirstRunTour from '../hooks/useFirstRunTour'
import { discoverDestinations, compareDestination, getRecentSearches, saveRecentSearch, deleteRecentSearch } from '../services/api'
import CompareTable from '../components/CompareTable'
import { buildCompareRequests, compareErrorReason, apiReturnDate } from '../utils/compare'
import { toRecentSearch, recentSearchToForm, describeRecentSearch } from '../utils/recentSearches'
import { fmtNumber } from '../i18n/format'

const INTEREST_IDS = ['food', 'history', 'adventure', 'culture', 'nature', 'shopping', 'nightlife', 'wellness', 'art', 'family']

// First-run tour of the Search page, in page order (the nav is sticky, so
// its step never scrolls). Steps whose element isn't on screen — no recent
// searches yet, or the nav collapsed on a phone — are skipped.
const buildTourSteps = (t) => [
  { id: 'recent', target: '[data-tour="recent-searches"]', title: t('tour.recent.title'), body: t('tour.recent.body') },
  { id: 'route', target: '[data-tour="route"]', title: t('tour.route.title'), body: t('tour.route.body') },
  { id: 'interests', target: '[data-tour="interests"]', title: t('tour.interests.title'), body: t('tour.interests.body') },
  { id: 'preferences', target: '[data-tour="nav-preferences"]', title: t('tour.preferences.title'), body: t('tour.preferences.body') },
  { id: 'plan', target: '[data-tour="plan-button"]', title: t('tour.plan.title'), body: t('tour.plan.body') },
  { id: 'my-plan', target: null, title: t('tour.myPlan.title'), body: t('tour.myPlan.body') },
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
  const { t } = useTranslation('search')
  const visaLabel = { 'visa-free': t('discover.visaFree'), 'visa-on-arrival': t('discover.visaOnArrival'), 'e-visa': t('discover.eVisa'), required: t('discover.visaRequired') }[dest.visa_type] || t('discover.visaVerify')
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
        {dest.visa_verified ? '' : '⚠️ '}{visaLabel}
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
          {t('discover.costRange', { low: fmtNumber(dest.estimated_cost_usd_low), high: fmtNumber(dest.estimated_cost_usd_high) })} <span className="text-xs font-normal text-gray-500">{t('discover.roughEstimate')}</span>
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

      <button type="button" onClick={onSelect} data-tid="search.destination-plan"
        className="mt-auto w-full py-2 px-3 bg-teal-600 hover:bg-teal-700 text-white text-sm font-medium rounded-lg transition-colors">
        {t('discover.planThisTrip')}
      </button>
    </div>
  )
}

export default function SearchPage() {
  const { t } = useTranslation('search')
  const tourSteps = useMemo(() => buildTourSteps(t), [t])
  const interestOptions = INTEREST_IDS.map(id => ({ id, label: t(`interests.${id}`) }))
  const { preferences, updatePreferences, token, user } = useAuth()
  const { setPendingSearchData, hasSearchResults, clearSearchResults } = useSearchData()
  const location = useLocation()
  const navigate = useNavigate()

  const today     = new Date().toISOString().split('T')[0]
  const nextWeek  = new Date(Date.now() + 7  * 86400000).toISOString().split('T')[0]
  const twoWeeks  = new Date(Date.now() + 14 * 86400000).toISOString().split('T')[0]

  const [mode, setMode] = useState('known')  // 'known' | 'discover' | 'compare' | 'import'
  // Plan from a link: the reviewed preview, and what to prefill the input
  // with (a deep-linked URL or a screenshot dropped anywhere on the page)
  const [importPreview, setImportPreview] = useState(null)
  const [importSeed, setImportSeed] = useState(null)
  // Arrived to import (deep link or a dropped screenshot): no first-run tour
  const [importEntry, setImportEntry] = useState(false)
  const formCardRef = useRef(null)
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
    visible: location.pathname === '/' && !hasSearchResults && mode === 'known' && !importEntry
      && !importLinkFromQuery(location.search),
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

  const startSearch = (form, extraStops, { preferenceInterests = form.interests } = {}) => {
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
      return_date: apiReturnDate(form.return_date),
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
      interests: preferenceInterests,
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
      ? t('recent.loadedShifted', { route })
      : t('recent.loaded', { route }))
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
        patch({ status: 'error', error: compareErrorReason(err) })
      }
    }
  }

  const retryCompareColumn = (index) => {
    if (compareColumns?.[index]?.status === 'loading') return
    loadCompareColumn(index)
  }

  const compareLoading = !!compareColumns?.some(c => c.status === 'loading')

  const handleCompare = (e) => {
    e.preventDefault()
    if (compareLoading) return
    const requests = buildCompareRequests(compareForm)
    if (requests.length < 2) {
      setCompareError(t('compare.needTwo'))
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
    // The compared request carries nulls; the form's inputs want ''
    const planForm = { ...form, destination, origin, departure_date, return_date: return_date ?? '',
      nationality, interests, budget_usd: budget_usd ?? '', adults, children, seniors, infants }
    setForm(planForm)
    setExtraStops([])
    setMode('known')
    startSearch(planForm, [])
  }

  // ── Plan from a link ──────────────────────────────────────────────────
  const openImport = (seed = null) => {
    setMode('import')
    setImportPreview(null)
    if (seed) {
      setImportEntry(true)
      setImportSeed({ ...seed, nonce: Date.now() })
    }
  }

  // /?import=<url> (e.g. from Chat) opens the import flow and starts reading
  useEffect(() => {
    const url = importLinkFromQuery(location.search)
    if (!url) return
    clearSearchResults() // show the Search page even if results were open
    openImport({ url, autoStart: true })
    navigate('/', { replace: true })
  }, [location.search])

  const handleImportPreview = (preview) => {
    setImportPreview(preview)
    track('import_preview_shown', 'search', { place_count: (preview.places || []).length })
    formCardRef.current?.scrollIntoView?.({ behavior: 'smooth', block: 'start' })
  }

  const handleImportPlan = ({ form: planForm, stops, placeCount }) => {
    track('import_planned', 'search', { place_count: placeCount, stops: stops.length + 1 })
    startSearch(planForm, stops, { preferenceInterests: form.interests })
  }

  // A screenshot dragged anywhere over the Search page opens the import tab
  const pageDrop = usePageFileDrop((files) => openImport({ files }))

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
      setDiscoverError(err.response?.data?.detail || t('discover.failed'))
    } finally {
      setDiscovering(false)
    }
  }

  const inputClass = "w-full px-3 py-2.5 border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-teal-400 focus:border-teal-400 transition-colors text-sm bg-white"
  const labelClass = "block text-sm font-medium text-gray-700 mb-1"

  return (
    <div {...pageDrop.handlers} className="relative">
      <OnboardingTour open={tour.open} steps={tourSteps} onClose={tour.close} />
      {pageDrop.dragging && (
        <div className="pointer-events-none fixed inset-0 z-50 flex items-center justify-center bg-amber-50/85 backdrop-blur-sm" aria-hidden="true">
          <div className="rounded-3xl border-2 border-dashed border-amber-400 bg-white/90 px-10 py-8 text-center shadow-xl">
            <ImagePlus size={36} className="mx-auto text-amber-600" />
            <p className="mt-3 font-display text-xl font-bold text-gray-900">{t('drop.title')}</p>
            <p className="mt-1 text-sm text-gray-500">{t('drop.body')}</p>
          </div>
        </div>
      )}

      {/* Hero */}
      <div className="max-w-4xl mx-auto px-4 pt-10 pb-6 text-center">
        <div className="inline-flex items-center gap-1.5 px-3 py-1 bg-teal-50 border border-teal-200 rounded-full text-teal-700 text-xs font-semibold mb-4">
          <Plane size={12} strokeWidth={2.5} />
          {t('hero.badge')}
        </div>
        <h1 className="font-display text-3xl sm:text-4xl md:text-5xl font-bold mb-3 tracking-tight leading-[1.1] bg-gradient-to-r from-teal-700 via-teal-600 to-sky-600 bg-clip-text text-transparent">{t('hero.title')}</h1>
        <p className="text-slate-500 text-lg">{t('hero.subtitle')}</p>
        <button type="button" onClick={() => { setMode('known'); tour.start() }} data-tid="search.tour-start"
          className="mt-2 text-sm font-medium text-teal-600 hover:text-teal-800 underline-offset-2 hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400 rounded">
          {t('hero.tour')}
        </button>
        {mode !== 'import' && (
          <p className="mt-3">
            <button type="button" onClick={() => openImport()} data-tid="search.import-open"
              className="inline-flex items-center gap-1.5 rounded-full bg-amber-100/80 px-3.5 py-1.5 text-sm text-amber-900 ring-1 ring-amber-200 hover:bg-amber-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-400">
              <Link2 size={14} /> {t('hero.importLead')} <span className="font-semibold">{t('hero.importLink')}</span>
            </button>
          </p>
        )}
      </div>

      {/* Form card */}
      <div className="max-w-4xl mx-auto px-4 pb-16 -mt-2">
        <div ref={formCardRef} className="bg-white rounded-3xl shadow-2xl ring-1 ring-gray-100 p-4 sm:p-6 md:p-8 scroll-mt-20">
          {/* Mode toggle */}
          <div className="flex flex-wrap items-center justify-center gap-1 sm:gap-2 mb-6 p-1 bg-gray-100 rounded-xl w-fit max-w-full mx-auto">
            <button type="button" data-tid="search.mode-known"
              onClick={() => setMode('known')}
              className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-all ${mode === 'known' ? 'bg-white shadow text-gray-900' : 'text-gray-500 hover:text-gray-700'}`}>
              {t('modes.known')}
            </button>
            <button type="button" data-tid="search.mode-discover"
              onClick={() => setMode('discover')}
              className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-all ${mode === 'discover' ? 'bg-white shadow text-gray-900' : 'text-gray-500 hover:text-gray-700'}`}>
              {t('modes.discover')}
            </button>
            <button type="button" data-tid="search.mode-compare"
              onClick={openCompare}
              className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-all ${mode === 'compare' ? 'bg-white shadow text-gray-900' : 'text-gray-500 hover:text-gray-700'}`}>
              {t('modes.compare')}
            </button>
            <button type="button" data-tid="search.mode-import"
              onClick={() => { if (mode !== 'import') openImport() }}
              className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-all ${mode === 'import' ? 'bg-white shadow text-gray-900' : 'text-gray-500 hover:text-gray-700'}`}>
              {t('modes.import')}
            </button>
          </div>

          {mode === 'import' && (importPreview ? (
            <ImportPreview key={importPreview.title + (importPreview.places || []).length}
              preview={importPreview} form={form} today={today} token={token}
              onPlan={handleImportPlan}
              onStartOver={() => { setImportPreview(null); setImportSeed(null) }} />
          ) : (
            <div className="space-y-4">
              <div className="text-center">
                <h2 className="font-display text-xl font-bold text-gray-900 sm:text-2xl">{t('import.heading')}</h2>
                <p className="mt-1 text-sm text-gray-500">{t('import.subheading')}</p>
              </div>
              <ImportPanel token={token} onPreview={handleImportPreview} seed={importSeed} />
            </div>
          ))}

          {mode === 'known' && (
            <RecentSearches entries={recentSearches} today={today}
              onLoad={handleLoadRecent} onRerun={handleRerunRecent} onRemove={handleRemoveRecent} />
          )}

          {mode === 'known' && <form onSubmit={handleSubmit} className="space-y-6">

            {recentNotice && (
              <div role="status" className="flex items-start gap-2 px-3 py-2 bg-teal-50 border border-teal-200 rounded-lg text-sm text-teal-800">
                <span className="flex-1">{recentNotice}</span>
                <button type="button" onClick={() => setRecentNotice(null)} aria-label={t('recent.dismiss')} data-tid="search.notice-dismiss"
                  className="text-teal-500 hover:text-teal-700 shrink-0 mt-0.5"><X size={14} /></button>
              </div>
            )}

            {/* Origin + Destination */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4" data-tour="route">
              <AirportSearch
                label={<span className="inline-flex items-center gap-1.5"><Plane size={13} /> {t('form.from')}</span>}
                value={form.origin}
                onChange={v => setForm(f => ({ ...f, origin: v }))}
                placeholder={t('form.cityOrAirport')}
                required
              />
              <AirportSearch
                label={<span className="inline-flex items-center gap-1.5"><MapPin size={13} /> {t('form.to')}</span>}
                value={form.destination}
                onChange={v => setForm(f => ({ ...f, destination: v }))}
                placeholder={t('form.cityOrAirport')}
                required
              />
            </div>

            {/* Intermediate stops — visited on the way to the To city */}
            <div className="space-y-3">
              {extraStops.map((stop, i) => (
                <div key={i} className="flex items-end gap-2">
                  <div className="flex-1">
                    <AirportSearch
                      label={<span className="inline-flex items-center gap-1.5"><MapPin size={13} /> {t('stops.label', { n: i + 1 })}</span>}
                      value={stop.city}
                      onChange={v => setExtraStops(stops => stops.map((s, j) => (j === i ? { ...s, city: v } : s)))}
                      placeholder={t('stops.placeholder')}
                      required
                    />
                  </div>
                  <div className="w-24">
                    <label className="block text-xs font-medium text-gray-500 mb-1">{t('stops.nights')} <span className="text-gray-300">{t('stops.optional')}</span></label>
                    <input type="number" min="1" max="30" value={stop.nights}
                      onChange={e => setExtraStops(stops => stops.map((s, j) => (j === i ? { ...s, nights: e.target.value } : s)))}
                      placeholder={t('stops.auto')}
                      className="w-full px-2.5 py-2.5 border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-teal-400 text-sm" />
                  </div>
                  <button type="button" title={t('stops.remove')} data-tid="search.stop-remove"
                    onClick={() => setExtraStops(stops => stops.filter((_, j) => j !== i))}
                    className="mb-1 p-2.5 rounded-lg border border-gray-200 text-gray-400 hover:text-red-500 hover:border-red-200 transition-colors">
                    <X size={14} />
                  </button>
                </div>
              ))}
              {extraStops.length < 3 && (
                <button type="button" data-tid="search.stop-add"
                  onClick={() => setExtraStops(stops => [...stops, { city: '', nights: '' }])}
                  className="inline-flex items-center gap-1.5 text-sm font-medium text-teal-600 hover:text-teal-800 transition-colors">
                  <Plus size={14} /> {t('stops.add')}
                </button>
              )}
              {extraStops.length > 0 && (
                <p className="text-xs text-gray-400">
                  <Trans t={t} i18nKey="stops.route"
                    values={{
                      origin: form.origin ? form.origin.split(',')[0] : t('stops.originFallback'),
                      stops: extraStops.filter(s => (s.city || '').trim()).map(s => s.city.split(',')[0]).join(' → ') || t('stops.stopsFallback'),
                      destination: form.destination ? form.destination.split(',')[0] : t('stops.destinationFallback'),
                    }}
                    components={{ b: <span className="font-medium text-gray-500" /> }} />
                  {' '}{t('stops.routeNote')}
                </p>
              )}
            </div>

            {/* Dates */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label className={labelClass}><span className="inline-flex items-center gap-1.5"><Calendar size={13} /> {t('form.departure')}</span></label>
                <input type="date" required value={form.departure_date} min={today}
                  onChange={e => setForm(f => ({ ...f, departure_date: e.target.value }))} className={inputClass} />
              </div>
              <div>
                <label className={labelClass}><span className="inline-flex items-center gap-1.5"><Calendar size={13} /> {t('form.return')}</span></label>
                <input type="date" value={form.return_date} min={form.departure_date}
                  onChange={e => setForm(f => ({ ...f, return_date: e.target.value }))} className={inputClass} />
              </div>
            </div>

            {/* Nationality + Budget + Travelers */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 items-start">
              <NationalitySearch
                label={<span className="inline-flex items-center gap-1.5"><Globe size={13} /> {t('form.nationality')}</span>}
                value={form.nationality}
                onChange={v => setForm(f => ({ ...f, nationality: v }))}
                placeholder={t('form.nationalityPlaceholder')}
                required
              />
              <div>
                <label className={labelClass}><span className="inline-flex items-center gap-1.5"><DollarSign size={13} /> {t('form.budget')}</span></label>
                <input type="number" value={form.budget_usd} min="0" step="100"
                  onChange={e => setForm(f => ({ ...f, budget_usd: e.target.value }))}
                  placeholder={t('form.optional')} className={inputClass} />
              </div>
              <div>
                <label className={labelClass}><span className="inline-flex items-center gap-1.5"><Users size={13} /> {t('form.travelers')}</span></label>
                <TravelerPanel form={form} setForm={setForm} />
              </div>
            </div>

            {/* Permits & Visas */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <TagInput label={t('form.permits')} value={form.residence_permits}
                onChange={v => setForm(f => ({ ...f, residence_permits: v }))} placeholder={t('form.permitsPlaceholder')} />
              <TagInput label={t('form.visas')} value={form.existing_visas}
                onChange={v => setForm(f => ({ ...f, existing_visas: v }))} placeholder={t('form.visasPlaceholder')} />
            </div>

            {/* Interests */}
            <div data-tour="interests">
              <label className={labelClass}>{t('form.interests')}</label>
              <div className="flex flex-wrap gap-2 mt-1">
                {interestOptions.map(({ id, label }) => (
                  <button key={id} type="button" onClick={() => toggleInterest(id)} data-tid={`search.interest-${id}`}
                    className={`px-3 py-1.5 rounded-full text-sm font-medium border-2 transition-all ${form.interests.includes(id) ? 'bg-teal-600 border-teal-600 text-white shadow-sm ring-2 ring-teal-200 ring-offset-1' : 'bg-white border-gray-200 text-gray-600 hover:border-teal-300 hover:text-teal-600'}`}>
                    {label}
                  </button>
                ))}
              </div>
            </div>

            {/* Serendipity dial */}
            <div>
              <div className="flex items-center justify-between mb-1">
                <label className={labelClass}>{t('dial.label')}</label>
                <span className="text-xs font-semibold text-teal-600">
                  {form.serendipity < 0.33 ? t('dial.classics') : form.serendipity > 0.66 ? t('dial.gems') : t('dial.balanced')}
                </span>
              </div>
              <input
                type="range" min="0" max="1" step="0.05"
                value={form.serendipity}
                onChange={e => setForm(f => ({ ...f, serendipity: parseFloat(e.target.value) }))}
                className="w-full accent-teal-600 cursor-pointer"
                aria-label={t('dial.aria')}
              />
              <div className="flex justify-between text-[11px] text-gray-400 mt-0.5">
                <span>{t('dial.iconic')}</span>
                <span>{t('dial.offBeaten')}</span>
              </div>
            </div>

            <button type="submit" data-tour="plan-button" data-tid="search.plan"
              className="w-full flex items-center justify-center gap-2 py-3.5 px-6 bg-gradient-to-r from-teal-600 to-teal-700 hover:from-teal-700 hover:to-teal-800 text-white font-semibold rounded-xl shadow-lg hover:shadow-xl active:scale-[0.99] transition-all text-base">
              <Search size={18} /> {t('form.plan')}
            </button>
          </form>}

          {mode === 'discover' && (
            <div className="space-y-6">
              {/* Origin + Dates row */}
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <AirportSearch
                  label={<span className="inline-flex items-center gap-1.5"><Plane size={13} /> {t('form.flyingFrom')}</span>}
                  value={discoverForm.origin}
                  onChange={v => setDiscoverForm(f => ({ ...f, origin: v }))}
                  placeholder={t('form.cityOrAirport')}
                  required
                />
                <div>
                  <label className={labelClass}><span className="inline-flex items-center gap-1.5"><Calendar size={13} /> {t('form.departure')}</span></label>
                  <input type="date" required value={discoverForm.departure_date} min={today}
                    onChange={e => setDiscoverForm(f => ({ ...f, departure_date: e.target.value }))} className={inputClass} />
                </div>
                <div>
                  <label className={labelClass}><span className="inline-flex items-center gap-1.5"><Calendar size={13} /> {t('form.return')}</span></label>
                  <input type="date" value={discoverForm.return_date} min={discoverForm.departure_date}
                    onChange={e => setDiscoverForm(f => ({ ...f, return_date: e.target.value }))} className={inputClass} />
                </div>
              </div>

              {/* Nationality + Budget */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <NationalitySearch
                  label={<span className="inline-flex items-center gap-1.5"><Globe size={13} /> {t('form.nationality')}</span>}
                  value={discoverForm.nationality}
                  onChange={v => setDiscoverForm(f => ({ ...f, nationality: v }))}
                  placeholder={t('form.nationalityPlaceholder')}
                  required
                />
                <div>
                  <label className={labelClass}><span className="inline-flex items-center gap-1.5"><DollarSign size={13} /> {t('form.budgetOptional')}</span></label>
                  <input type="number" value={discoverForm.budget_usd} min="0" step="100"
                    onChange={e => setDiscoverForm(f => ({ ...f, budget_usd: e.target.value }))}
                    placeholder={t('form.totalBudget')} className={inputClass} />
                </div>
              </div>

              {/* Interests */}
              <div>
                <label className={labelClass}>{t('form.interestsDiscover')}</label>
                <div className="flex flex-wrap gap-2 mt-1">
                  {interestOptions.map(({ id, label }) => (
                    <button key={id} type="button" data-tid={`search.discover-interest-${id}`}
                      onClick={() => setDiscoverForm(f => ({ ...f, interests: f.interests.includes(id) ? f.interests.filter(i => i !== id) : [...f.interests, id] }))}
                      className={`px-3 py-1.5 rounded-full text-sm font-medium border-2 transition-all ${discoverForm.interests.includes(id) ? 'bg-teal-600 border-teal-600 text-white shadow-sm ring-2 ring-teal-200 ring-offset-1' : 'bg-white border-gray-200 text-gray-600 hover:border-teal-300 hover:text-teal-600'}`}>
                      {label}
                    </button>
                  ))}
                </div>
              </div>

              {/* Submit button */}
              <button type="button" data-tid="search.discover-submit"
                disabled={discovering || !discoverForm.origin || !discoverForm.nationality}
                onClick={handleDiscover}
                className="w-full flex items-center justify-center gap-2 py-3.5 px-6 bg-gradient-to-r from-teal-600 to-teal-700 hover:from-teal-700 hover:to-teal-800 disabled:opacity-50 disabled:cursor-not-allowed text-white font-semibold rounded-xl shadow-lg hover:shadow-xl active:scale-[0.99] transition-all text-base">
                {discovering ? (
                  <><span className="animate-spin inline-block w-4 h-4 border-2 border-white border-t-transparent rounded-full" /> {t('discover.finding')}</>
                ) : (
                  <><Search size={18} /> {t('discover.find')}</>
                )}
              </button>

              {/* Error */}
              {discoverError && (
                <p className="text-center text-red-500 text-sm">{discoverError}</p>
              )}

              {/* Results: DestinationCard grid */}
              {destinations && destinations.length > 0 && (
                <div>
                  <h3 className="text-lg font-semibold text-gray-800 mb-3">{t('discover.picks')}</h3>
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
                <p className="text-center text-gray-500 text-sm py-4">{t('discover.none')}</p>
              )}
            </div>
          )}

          {mode === 'compare' && compareForm && (
            <div className="space-y-6">
              <form onSubmit={handleCompare} className="space-y-6">
                <p className="text-sm text-gray-500 text-center">{t('compare.intro')}</p>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <AirportSearch
                    label={<span className="inline-flex items-center gap-1.5"><Plane size={13} /> {t('form.from')}</span>}
                    value={compareForm.origin}
                    onChange={v => setCompareForm(c => ({ ...c, origin: v }))}
                    placeholder={t('form.cityOrAirport')}
                    required
                  />
                </div>

                <div className="space-y-3">
                  {compareForm.destinations.map((dest, i) => (
                    <div key={i} className="flex items-end gap-2">
                      <div className="flex-1">
                        <AirportSearch
                          label={<span className="inline-flex items-center gap-1.5"><MapPin size={13} /> {t('compare.destination', { n: i + 1 })}</span>}
                          value={dest}
                          onChange={v => setCompareDestination(i, v)}
                          placeholder={t('form.cityOrAirport')}
                        />
                      </div>
                      {compareForm.destinations.length > 2 && (
                        <button type="button" title={t('compare.removeDestination')} aria-label={t('compare.removeDestinationN', { n: i + 1 })} data-tid="search.compare-remove"
                          onClick={() => setCompareForm(c => ({ ...c, destinations: c.destinations.filter((_, j) => j !== i) }))}
                          className="mb-1 p-2.5 rounded-lg border border-gray-200 text-gray-400 hover:text-red-500 hover:border-red-200 transition-colors">
                          <X size={14} />
                        </button>
                      )}
                    </div>
                  ))}
                  {compareForm.destinations.length < 3 && (
                    <button type="button" data-tid="search.compare-add"
                      onClick={() => setCompareForm(c => ({ ...c, destinations: [...c.destinations, ''] }))}
                      className="inline-flex items-center gap-1.5 text-sm font-medium text-teal-600 hover:text-teal-800 transition-colors">
                      <Plus size={14} /> {t('compare.addAnother')}
                    </button>
                  )}
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div>
                    <label className={labelClass}><span className="inline-flex items-center gap-1.5"><Calendar size={13} /> {t('form.departure')}</span></label>
                    <input type="date" required value={compareForm.departure_date} min={today}
                      onChange={e => setCompareForm(c => ({ ...c, departure_date: e.target.value }))} className={inputClass} />
                  </div>
                  <div>
                    <label className={labelClass}><span className="inline-flex items-center gap-1.5"><Calendar size={13} /> {t('form.return')}</span></label>
                    <input type="date" value={compareForm.return_date} min={compareForm.departure_date}
                      onChange={e => setCompareForm(c => ({ ...c, return_date: e.target.value }))} className={inputClass} />
                  </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-3 gap-4 items-start">
                  <NationalitySearch
                    label={<span className="inline-flex items-center gap-1.5"><Globe size={13} /> {t('form.nationality')}</span>}
                    value={compareForm.nationality}
                    onChange={v => setCompareForm(c => ({ ...c, nationality: v }))}
                    placeholder={t('form.nationalityPlaceholder')}
                    required
                  />
                  <div>
                    <label className={labelClass}><span className="inline-flex items-center gap-1.5"><DollarSign size={13} /> {t('form.budget')}</span></label>
                    <input type="number" value={compareForm.budget_usd} min="0" step="100"
                      onChange={e => setCompareForm(c => ({ ...c, budget_usd: e.target.value }))}
                      placeholder={t('form.optional')} className={inputClass} />
                  </div>
                  <div>
                    <label className={labelClass}><span className="inline-flex items-center gap-1.5"><Users size={13} /> {t('form.travelers')}</span></label>
                    <TravelerPanel form={compareForm} setForm={setCompareForm} />
                  </div>
                </div>

                <div>
                  <label className={labelClass}>{t('form.interests')}</label>
                  <div className="flex flex-wrap gap-2 mt-1">
                    {interestOptions.map(({ id, label }) => (
                      <button key={id} type="button" data-tid={`search.compare-interest-${id}`}
                        onClick={() => setCompareForm(c => ({ ...c, interests: c.interests.includes(id) ? c.interests.filter(i => i !== id) : [...c.interests, id] }))}
                        className={`px-3 py-1.5 rounded-full text-sm font-medium border-2 transition-all ${compareForm.interests.includes(id) ? 'bg-teal-600 border-teal-600 text-white shadow-sm ring-2 ring-teal-200 ring-offset-1' : 'bg-white border-gray-200 text-gray-600 hover:border-teal-300 hover:text-teal-600'}`}>
                        {label}
                      </button>
                    ))}
                  </div>
                </div>

                {compareError && <p role="alert" className="text-center text-red-500 text-sm">{compareError}</p>}

                <button type="submit" disabled={compareLoading} data-tid="search.compare-submit"
                  className="w-full flex items-center justify-center gap-2 py-3.5 px-6 bg-gradient-to-r from-teal-600 to-teal-700 hover:from-teal-700 hover:to-teal-800 text-white font-semibold rounded-xl shadow-lg hover:shadow-xl active:scale-[0.99] transition-all text-base disabled:opacity-60 disabled:cursor-not-allowed">
                  <Search size={18} /> {compareLoading ? t('compare.comparing') : t('compare.submit')}
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
