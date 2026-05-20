import { useState, useEffect, useRef, startTransition } from 'react'
import {
  ArrowLeft, Plane, Hotel, MapPin, Shield, Smartphone,
  Lightbulb, Calendar, CheckCircle2, Loader2, Clock,
  Star, AlertTriangle, Info, AlertCircle, ExternalLink,
  DollarSign, Users, Globe, Zap, BookmarkPlus, X,
  ChevronDown, ChevronUp, Check, PenLine, Trash2,
  LogOut, User, Save, RefreshCw, Bookmark, Plus, Minus, Eye,
  Bus, Map, SlidersHorizontal, Wifi, Bath
} from 'lucide-react'
import { streamSearch, searchFlightsFiltered, searchHotelsFiltered, searchActivitiesFiltered } from '../services/api'
import { useAuth } from '../context/AuthContext'
import { useSearchData } from '../context/SearchDataContext'
import { generatePlanName, computePlanCost, getBudgetStatus, countSelections, EMPTY_SELECTIONS } from '../utils/planHelpers'
import { track } from '../utils/analytics'
import AirportSearch from '../components/ui/AirportSearch'
import TagInput from '../components/ui/TagInput'
import PlanViewModal from '../components/PlanViewModal'

// ─── Constants ───────────────────────────────────────────────────────────────

const AGENT_CONFIG = {
  flights:        { label: 'Flights',        icon: Plane,       color: 'blue'   },
  hotels:         { label: 'Hotels',         icon: Hotel,       color: 'purple' },
  activities:     { label: 'Activities',     icon: MapPin,      color: 'green'  },
  places_to_see:  { label: 'Places to See',  icon: Map,         color: 'lime'   },
  visa:           { label: 'Visa',           icon: Shield,      color: 'orange' },
  sim:            { label: 'SIM Cards',      icon: Smartphone,  color: 'pink'   },
  tips:           { label: 'Travel Tips',    icon: Lightbulb,   color: 'yellow' },
  getting_around: { label: 'Getting Around', icon: Bus,         color: 'cyan'   },
  forex:          { label: 'Currency & Forex', icon: DollarSign, color: 'emerald'},
  itinerary:      { label: 'Itinerary',      icon: Calendar,    color: 'indigo' },
}
const AGENT_ORDER = ['flights', 'hotels', 'activities', 'places_to_see', 'visa', 'sim', 'tips', 'getting_around', 'forex', 'itinerary']

const COLOR_MAP = {
  blue:   { badge: 'bg-sky-50 text-sky-700 border-sky-200',       header: 'from-sky-400 to-sky-500' },
  purple: { badge: 'bg-violet-50 text-violet-700 border-violet-200', header: 'from-violet-400 to-violet-500' },
  green:  { badge: 'bg-emerald-50 text-emerald-700 border-emerald-200', header: 'from-emerald-500 to-emerald-600' },
  orange: { badge: 'bg-orange-50 text-orange-700 border-orange-200', header: 'from-amber-400 to-orange-400' },
  pink:   { badge: 'bg-rose-50 text-rose-700 border-rose-200',    header: 'from-rose-400 to-rose-500' },
  yellow: { badge: 'bg-amber-50 text-amber-700 border-amber-200', header: 'from-amber-400 to-yellow-400' },
  cyan:   { badge: 'bg-cyan-50 text-cyan-700 border-cyan-200',    header: 'from-cyan-500 to-cyan-600' },
  emerald:{ badge: 'bg-emerald-50 text-emerald-700 border-emerald-200', header: 'from-emerald-500 to-emerald-600' },
  indigo: { badge: 'bg-teal-50 text-teal-700 border-teal-200',    header: 'from-teal-500 to-teal-600' },
  lime:   { badge: 'bg-lime-50 text-lime-700 border-lime-200',    header: 'from-lime-500 to-green-500' },
}

const INTEREST_LABELS = { food:'🍜 Food',history:'🏛️ History',adventure:'🧗 Adventure',culture:'🎭 Culture',nature:'🌿 Nature',shopping:'🛍️ Shopping',nightlife:'🌙 Nightlife',wellness:'🧘 Wellness',art:'🎨 Art',family:'👨‍👩‍👧 Family' }

// ─── Small sub-components ────────────────────────────────────────────────────

const BADGE_LABELS = { flights: 'Flights', hotels: 'Hotels', activities: 'Activities', places_to_see: 'Places', visa: 'Visa', sim: 'SIM', tips: 'Tips', getting_around: 'Transport', forex: 'Forex', itinerary: 'Itinerary' }

function AgentBadge({ agent, status, onClick }) {
  const { icon: Icon, color } = AGENT_CONFIG[agent]
  const badgeLabel = BADGE_LABELS[agent] || AGENT_CONFIG[agent].label
  const isClickable = status !== 'waiting'
  return (
    <button
      onClick={() => isClickable && onClick?.(agent)}
      className={`flex items-center gap-1 px-2 py-1 rounded-full border text-[11px] font-medium ${COLOR_MAP[color].badge} ${isClickable ? 'cursor-pointer hover:ring-2 hover:ring-offset-1 hover:ring-current/20 transition-all' : 'opacity-60 cursor-default'}`}
    >
      <Icon size={11} /> <span>{badgeLabel}</span>
      {status === 'loading'   && <Loader2 size={10} className="animate-spin" />}
      {status === 'enhancing' && <Loader2 size={10} className="animate-spin text-amber-500" />}
      {status === 'done'      && <CheckCircle2 size={10} className="text-green-600" />}
      {status === 'waiting'   && <div className="w-1.5 h-1.5 rounded-full bg-current opacity-30" />}
    </button>
  )
}

function SectionHeader({ agent, status, isOpen, onToggle, actions }) {
  const { label, icon: Icon, color } = AGENT_CONFIG[agent]
  return (
    <div
      onClick={onToggle}
      className={`flex items-center gap-3 p-4 w-full text-left ${isOpen ? 'rounded-t-xl' : 'rounded-xl'} bg-gradient-to-r ${COLOR_MAP[color].header} text-white transition-all cursor-pointer`}
    >
      <Icon size={20} /> <h2 className="font-semibold text-lg flex-1">{label}</h2>
      {actions}
      {status === 'loading'   && <Loader2 size={16} className="animate-spin" />}
      {status === 'enhancing' && <span className="flex items-center gap-1.5 text-xs bg-white/20 px-2 py-0.5 rounded-full"><Loader2 size={12} className="animate-spin" /> Enhancing…</span>}
      {status === 'done'      && <CheckCircle2 size={16} className="opacity-80" />}
      <ChevronDown size={18} className={`transition-transform duration-200 ${isOpen ? 'rotate-180' : ''}`} />
    </div>
  )
}

const LOADING_MESSAGES = {
  flights: [
    "Scanning airlines for the best deals...",
    "Comparing prices across carriers...",
    "Checking direct and connecting flights..."
  ],
  hotels: [
    "Finding hotels across all budgets...",
    "Checking room availability...",
    "Comparing luxury to budget stays..."
  ],
  activities: [
    "Discovering things to do...",
    "Matching activities to your interests...",
    "Finding hidden gems and must-sees..."
  ],
  visa: [
    "Checking entry requirements...",
    "Verifying visa and passport rules...",
    "Looking up vaccination requirements..."
  ],
  sim: [
    "Finding the best SIM and eSIM plans...",
    "Comparing data packages...",
    "Checking coverage and prices..."
  ],
  tips: [
    "Gathering local travel tips...",
    "Checking safety advisories...",
    "Finding cultural etiquette tips..."
  ],
  getting_around: [
    "Mapping out transport options...",
    "Checking public transit routes...",
    "Finding the best ways to get around..."
  ],
  forex: [
    "Checking current exchange rates...",
    "Finding the best places to exchange money...",
    "Researching card and ATM options..."
  ],
  itinerary: [
    "Building your day-by-day plan...",
    "Organizing activities by day...",
    "Crafting the perfect itinerary..."
  ],
  places_to_see: [
    "Finding must-see attractions...",
    "Searching Google for top landmarks...",
    "Discovering iconic sites and hidden gems..."
  ],
}

function Skeleton({ agent }) {
  const [msgIdx, setMsgIdx] = useState(0)
  const msgs = LOADING_MESSAGES[agent] || ["Loading..."]

  useEffect(() => {
    const timer = setInterval(() => setMsgIdx(i => (i + 1) % msgs.length), 3000)
    return () => clearInterval(timer)
  }, [msgs.length])

  return (
    <div className="p-6 flex flex-col items-center justify-center gap-3">
      <div className="flex items-center gap-2 text-sm text-gray-500">
        <Loader2 size={16} className="animate-spin text-teal-500" />
        <span className="animate-pulse">{msgs[msgIdx]}</span>
      </div>
      <div className="w-full space-y-3 animate-pulse">
        <div className="flex gap-3"><div className="h-4 bg-gray-200 rounded w-3/4" /><div className="h-4 bg-gray-100 rounded w-1/4" /></div>
        <div className="flex gap-3"><div className="h-4 bg-gray-200 rounded w-1/2" /><div className="h-4 bg-gray-100 rounded w-1/2" /></div>
        <div className="flex gap-3"><div className="h-4 bg-gray-200 rounded w-5/6" /><div className="h-4 bg-gray-100 rounded w-1/6" /></div>
      </div>
    </div>
  )
}

// ─── Section renderers ────────────────────────────────────────────────────────

function FlightLeg({ leg, direction }) {
  if (!leg) return null
  const fmtDur = leg.duration_minutes ? `${Math.floor(leg.duration_minutes/60)}h ${leg.duration_minutes%60}m` : null
  return (
    <div className="text-xs space-y-1">
      <div className="flex items-center gap-2">
        <span className={`shrink-0 px-1.5 py-0.5 rounded font-semibold ${direction === 'outbound' ? 'bg-sky-100 text-sky-700' : 'bg-violet-100 text-violet-700'}`}>
          {direction === 'outbound' ? 'Depart' : 'Return'}
        </span>
        <div className="flex-1 min-w-0">
          <span className="font-medium text-gray-900">{leg.airline || '—'}</span>
          {leg.flight_number && <span className="text-gray-400 ml-1">{leg.flight_number}</span>}
        </div>
        <span className={`shrink-0 px-1.5 py-0.5 rounded-full font-medium ${leg.stops === 0 ? 'bg-green-100 text-green-700' : 'bg-orange-100 text-orange-700'}`}>
          {leg.stops === 0 ? 'Direct' : `${leg.stops} stop${leg.stops > 1 ? 's' : ''}`}
        </span>
      </div>
      <div className="flex items-center gap-2 text-gray-500 pl-1 flex-wrap">
        <span>{leg.origin || '—'} → {leg.destination || '—'}</span>
        <span className="text-gray-300">·</span>
        <span>{leg.departure_time || '—'} – {leg.arrival_time || '—'}</span>
        {fmtDur && <><span className="text-gray-300">·</span><span className="text-gray-400">{fmtDur}</span></>}
      </div>
    </div>
  )
}

function FlightsSection({ data, selections, onSelect }) {
  if (!data?.results?.length) return <div className="p-4 text-sm text-gray-500">No flights found</div>
  const selected = selections.flight

  // Detect format: new round-trip (has outbound/return objects) vs legacy flat
  const isRoundTripFormat = data.results[0]?.outbound != null

  if (!isRoundTripFormat) {
    // Legacy flat format fallback
    return (
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-gray-600 text-xs uppercase">
            <tr>
              <th className="px-3 py-3 w-8"></th>
              <th className="px-4 py-3 text-left">Airline</th>
              <th className="px-4 py-3 text-right">Price</th>
              <th className="px-4 py-3 text-center">Stops</th>
              <th className="px-4 py-3 text-center">Duration</th>
              <th className="px-4 py-3 text-center">Depart / Arrive</th>
              <th className="px-4 py-3 text-center">Source</th>
              <th className="px-4 py-3 text-center">Book</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {data.results.map((f, i) => {
              const isSelected = selected && selected.airline === f.airline && selected.price_usd === f.price_usd
              return (
                <tr key={i} onClick={() => onSelect('flight', isSelected ? null : f)}
                  className={`cursor-pointer transition-colors ${isSelected ? 'bg-teal-50 ring-1 ring-inset ring-teal-300' : 'hover:bg-gray-50'}`}>
                  <td className="px-3 py-3 text-center">
                    <div className={`w-4 h-4 rounded-full border-2 mx-auto flex items-center justify-center ${isSelected ? 'border-teal-600 bg-teal-600' : 'border-gray-300'}`}>
                      {isSelected && <div className="w-2 h-2 bg-white rounded-full" />}
                    </div>
                  </td>
                  <td className="px-4 py-3 font-medium">{f.airline} {f.flight_number && <span className="text-xs text-gray-400 ml-1">{f.flight_number}</span>}</td>
                  <td className="px-4 py-3 text-right font-bold text-teal-700">{f.price_usd ? `$${f.price_usd.toLocaleString()}` : '—'}</td>
                  <td className="px-4 py-3 text-center">
                    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${f.stops === 0 ? 'bg-green-100 text-green-700' : 'bg-orange-100 text-orange-700'}`}>
                      {f.stops === 0 ? 'Non-stop' : `${f.stops} stop${f.stops > 1 ? 's' : ''}`}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-center text-gray-600">{f.duration_minutes ? `${Math.floor(f.duration_minutes/60)}h ${f.duration_minutes%60}m` : '—'}</td>
                  <td className="px-4 py-3 text-center text-gray-500 text-xs">{f.departure_time || '—'} → {f.arrival_time || '—'}</td>
                  <td className="px-4 py-3 text-center">{f.source && <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-sky-50 text-sky-600 border border-sky-200">{f.source.replace(/_/g,' ')}</span>}</td>
                  <td className="px-4 py-3 text-center">
                    {f.booking_url && <a href={f.booking_url} target="_blank" rel="noopener noreferrer" onClick={e => e.stopPropagation()} className="text-teal-500 hover:text-teal-700"><ExternalLink size={13} /></a>}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    )
  }

  // Round-trip card layout
  return (
    <div className="space-y-3 p-4">
      {data.results.map((f, i) => {
        const isSelected = selected && selected === f || (selected?.price_usd === f.price_usd && selected?.outbound?.airline === f.outbound?.airline)
        const isOneWay = f.trip_type === 'one_way' || !f.return
        return (
          <div key={i}
            onClick={() => onSelect('flight', isSelected ? null : f)}
            className={`border rounded-xl p-4 cursor-pointer transition-all ${isSelected ? 'border-teal-400 ring-2 ring-teal-300 bg-teal-50' : 'border-gray-200 hover:shadow-md'}`}
          >
            <div className="flex items-start justify-between mb-3">
              <div className="flex items-center gap-2">
                <div className={`w-5 h-5 rounded-full border-2 flex items-center justify-center ${isSelected ? 'border-teal-600 bg-teal-600' : 'border-gray-300'}`}>
                  {isSelected && <div className="w-2.5 h-2.5 bg-white rounded-full" />}
                </div>
                <span className={`px-2 py-0.5 rounded-full text-xs font-semibold ${isOneWay ? 'bg-gray-100 text-gray-600' : 'bg-sky-100 text-sky-700'}`}>
                  {isOneWay ? 'One-way' : 'Round-trip'}
                </span>
                {f.source && <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-sky-50 text-sky-600 border border-sky-200">{f.source.replace(/_/g,' ')}</span>}
              </div>
              <div className="text-right">
                <p className="text-lg font-bold text-teal-700">{f.price_usd ? `$${f.price_usd.toLocaleString()}` : '—'}</p>
                <p className="text-xs text-gray-400">{isOneWay ? 'per person' : 'round-trip / person'}</p>
              </div>
            </div>

            {/* Outbound leg */}
            <FlightLeg leg={f.outbound} direction="outbound" />

            {/* Return leg */}
            {f.return && (
              <>
                <div className="border-t border-dashed border-gray-200 my-2" />
                <FlightLeg leg={f.return} direction="return" />
              </>
            )}

            {/* Booking link */}
            {f.booking_url && (
              <div className="mt-2 pt-2 border-t border-gray-100 flex items-center justify-between">
                <a href={f.booking_url} target="_blank" rel="noopener noreferrer" onClick={e => e.stopPropagation()}
                  className="flex items-center gap-1 text-xs text-teal-600 hover:text-teal-800 font-medium">
                  <ExternalLink size={11} /> Book this flight
                </a>
                {isSelected && <span className="flex items-center gap-1 text-xs font-semibold text-teal-700"><Check size={12} /> Added to Plan</span>}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

// ─── Flight Filter Modal ─────────────────────────────────────────────────────

function FlightFilterModal({ isOpen, onClose, onApply, currentResults, isLoading }) {
  const [stops, setStops] = useState(null)
  const [maxPrice, setMaxPrice] = useState(null)
  const [depEarliest, setDepEarliest] = useState(0)
  const [depLatest, setDepLatest] = useState(24)
  const [arrEarliest, setArrEarliest] = useState(0)
  const [arrLatest, setArrLatest] = useState(24)

  const prices = (currentResults?.results || []).map(f => f.price_usd).filter(Boolean)
  const priceCeil = prices.length ? Math.ceil(Math.max(...prices) * 1.5 / 100) * 100 : 5000
  const priceFloor = 100
  const effectiveMaxPrice = maxPrice ?? priceCeil

  if (!isOpen) return null

  const fmtHour = (h) => {
    const hh = Math.floor(h)
    return `${hh.toString().padStart(2, '0')}:00`
  }

  const handleApply = () => {
    const filters = {}
    if (stops !== null) filters.max_stops = stops
    if (maxPrice !== null) filters.max_price_usd = maxPrice
    if (depEarliest > 0) filters.departure_time_earliest = fmtHour(depEarliest)
    if (depLatest < 24) filters.departure_time_latest = fmtHour(depLatest)
    if (arrEarliest > 0) filters.arrival_time_earliest = fmtHour(arrEarliest)
    if (arrLatest < 24) filters.arrival_time_latest = fmtHour(arrLatest)
    onApply(filters)
  }

  const handleReset = () => {
    setStops(null)
    setMaxPrice(null)
    setDepEarliest(0)
    setDepLatest(24)
    setArrEarliest(0)
    setArrLatest(24)
  }

  const hasFilters = stops !== null || maxPrice !== null || depEarliest > 0 || depLatest < 24 || arrEarliest > 0 || arrLatest < 24
  const activeCount = (stops !== null ? 1 : 0) + (maxPrice !== null ? 1 : 0) + (depEarliest > 0 || depLatest < 24 ? 1 : 0) + (arrEarliest > 0 || arrLatest < 24 ? 1 : 0)

  const stopsOptions = [
    { value: null, label: 'Any' },
    { value: 0, label: 'Non-stop' },
    { value: 1, label: '1 Stop' },
    { value: 2, label: '2 Stops' },
  ]

  const sliderThumb = '[&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-4 [&::-webkit-slider-thumb]:h-4 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-sky-500 [&::-webkit-slider-thumb]:cursor-pointer [&::-webkit-slider-thumb]:shadow-md [&::-webkit-slider-thumb]:border-2 [&::-webkit-slider-thumb]:border-white'

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm" onClick={onClose}>
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md mx-4 overflow-hidden animate-in" onClick={e => e.stopPropagation()}>
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100 bg-gradient-to-r from-sky-50 to-white">
          <h3 className="font-bold text-lg text-gray-800 flex items-center gap-2">
            <SlidersHorizontal size={18} className="text-sky-500" /> Flight Filters
          </h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 transition-colors"><X size={18} /></button>
        </div>

        <div className="px-6 py-5 space-y-6 max-h-[65vh] overflow-y-auto">
          {/* Stops */}
          <div>
            <label className="block text-sm font-semibold text-gray-700 mb-2">Number of Stops</label>
            <div className="grid grid-cols-4 gap-2">
              {stopsOptions.map(opt => (
                <button key={String(opt.value)} type="button" onClick={() => setStops(opt.value)}
                  className={`px-3 py-2 rounded-lg text-sm font-medium border-2 transition-all ${stops === opt.value ? 'bg-sky-500 border-sky-500 text-white shadow-sm' : 'bg-white border-gray-200 text-gray-600 hover:border-sky-300 hover:text-sky-600'}`}>
                  {opt.label}
                </button>
              ))}
            </div>
          </div>

          {/* Max Price */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="text-sm font-semibold text-gray-700">Max Price (per person)</label>
              <span className="text-sm font-bold text-sky-600">{maxPrice !== null ? `$${effectiveMaxPrice.toLocaleString()}` : 'Any'}</span>
            </div>
            <input
              type="range"
              min={priceFloor} max={priceCeil} step={50}
              value={effectiveMaxPrice}
              onChange={e => setMaxPrice(Number(e.target.value))}
              className={`w-full h-2 bg-gray-200 rounded-full appearance-none cursor-pointer accent-sky-500 ${sliderThumb}`}
            />
            <div className="flex justify-between text-xs text-gray-400 mt-1">
              <span>${priceFloor}</span>
              <span>${priceCeil.toLocaleString()}</span>
            </div>
          </div>

          {/* Departure Time */}
          <div>
            <label className="block text-sm font-semibold text-gray-700 mb-2">Departure Time</label>
            <div className="space-y-3">
              <div>
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xs text-gray-500">Earliest</span>
                  <span className="text-xs font-semibold text-sky-600">{fmtHour(depEarliest)}</span>
                </div>
                <input type="range" min={0} max={23} step={1} value={depEarliest}
                  onChange={e => { const v = Number(e.target.value); setDepEarliest(Math.min(v, depLatest - 1)) }}
                  className={`w-full h-2 bg-gray-200 rounded-full appearance-none cursor-pointer accent-sky-500 ${sliderThumb}`}
                />
              </div>
              <div>
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xs text-gray-500">Latest</span>
                  <span className="text-xs font-semibold text-sky-600">{fmtHour(depLatest)}</span>
                </div>
                <input type="range" min={1} max={24} step={1} value={depLatest}
                  onChange={e => { const v = Number(e.target.value); setDepLatest(Math.max(v, depEarliest + 1)) }}
                  className={`w-full h-2 bg-gray-200 rounded-full appearance-none cursor-pointer accent-sky-500 ${sliderThumb}`}
                />
              </div>
              <div className="flex justify-between text-xs text-gray-400">
                <span>00:00</span><span>06:00</span><span>12:00</span><span>18:00</span><span>24:00</span>
              </div>
            </div>
          </div>

          {/* Arrival Time */}
          <div>
            <label className="block text-sm font-semibold text-gray-700 mb-2">Arrival Time</label>
            <div className="space-y-3">
              <div>
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xs text-gray-500">Earliest</span>
                  <span className="text-xs font-semibold text-sky-600">{fmtHour(arrEarliest)}</span>
                </div>
                <input type="range" min={0} max={23} step={1} value={arrEarliest}
                  onChange={e => { const v = Number(e.target.value); setArrEarliest(Math.min(v, arrLatest - 1)) }}
                  className={`w-full h-2 bg-gray-200 rounded-full appearance-none cursor-pointer accent-sky-500 ${sliderThumb}`}
                />
              </div>
              <div>
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xs text-gray-500">Latest</span>
                  <span className="text-xs font-semibold text-sky-600">{fmtHour(arrLatest)}</span>
                </div>
                <input type="range" min={1} max={24} step={1} value={arrLatest}
                  onChange={e => { const v = Number(e.target.value); setArrLatest(Math.max(v, arrEarliest + 1)) }}
                  className={`w-full h-2 bg-gray-200 rounded-full appearance-none cursor-pointer accent-sky-500 ${sliderThumb}`}
                />
              </div>
              <div className="flex justify-between text-xs text-gray-400">
                <span>00:00</span><span>06:00</span><span>12:00</span><span>18:00</span><span>24:00</span>
              </div>
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-gray-100 bg-gray-50 flex items-center justify-between">
          <button onClick={handleReset} disabled={!hasFilters}
            className={`text-sm font-medium transition-colors ${hasFilters ? 'text-gray-600 hover:text-red-600' : 'text-gray-300 cursor-default'}`}>
            Reset All
          </button>
          <button onClick={handleApply} disabled={isLoading}
            className="flex items-center gap-2 px-5 py-2.5 bg-sky-500 text-white text-sm font-semibold rounded-xl hover:bg-sky-600 disabled:opacity-60 transition-all shadow-md">
            {isLoading ? <><Loader2 size={14} className="animate-spin" /> Searching...</> : <><SlidersHorizontal size={14} /> Apply Filters{activeCount > 0 ? ` (${activeCount})` : ''}</>}
          </button>
        </div>
      </div>
    </div>
  )
}

function HotelsSection({ data, selections, onSelect }) {
  if (!data?.results?.length) return <div className="p-4 text-sm text-gray-500">No hotels found</div>
  const selected = selections.hotel
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4 p-4">
      {data.results.map((h, i) => {
        const isSelected = selected && selected.name === h.name
        return (
          <div key={i} className={`border rounded-xl p-4 transition-all ${isSelected ? 'border-purple-400 ring-2 ring-purple-300 bg-purple-50' : 'border-gray-200 hover:shadow-md'}`}>
            <div className="flex justify-between items-start mb-2">
              <div className="flex-1 min-w-0 mr-2">
                <h3 className="font-semibold text-gray-900 truncate">{h.name}</h3>
                <p className="text-xs text-gray-500 mt-0.5">{h.location}</p>
              </div>
              <div className="text-right shrink-0">
                <p className="font-bold text-purple-700">${h.price_per_night_usd?.toLocaleString()}<span className="text-xs font-normal text-gray-500">/night</span></p>
                {h.total_price_usd && <p className="text-xs text-gray-400">${h.total_price_usd.toLocaleString()} total</p>}
              </div>
            </div>
            <div className="flex items-center gap-2 mb-2">
              <div className="flex">{[...Array(Math.round(h.star_rating || 0))].map((_, j) => <Star key={j} size={11} className="text-yellow-400 fill-yellow-400" />)}</div>
              {h.review_score && <span className="text-xs text-gray-500">{h.review_score}/10</span>}
            </div>
            {h.amenities?.length > 0 && (
              <div className="flex flex-wrap gap-1 mb-3">
                {h.amenities.slice(0, 4).map(a => <span key={a} className="px-1.5 py-0.5 bg-gray-100 text-gray-600 rounded text-xs">{a}</span>)}
                {h.amenities.length > 4 && <span className="px-1.5 py-0.5 bg-gray-100 text-gray-500 rounded text-xs">+{h.amenities.length-4}</span>}
              </div>
            )}
            <div className="flex items-center justify-between mt-2">
              <div className="flex items-center gap-2">
                {h.booking_url && <a href={h.booking_url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 text-xs text-purple-600 hover:text-purple-800 font-medium"><ExternalLink size={11} /> View &amp; Book</a>}
                {h.source && <span className="px-1.5 py-0.5 rounded text-xs bg-violet-50 text-violet-500 border border-violet-200">{h.source}</span>}
              </div>
              <button type="button" onClick={() => onSelect('hotel', isSelected ? null : h)}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold transition-all ${isSelected ? 'bg-purple-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-purple-100 hover:text-purple-700'}`}>
                {isSelected ? <><Check size={11}/> Added to Plan</> : <><Plus size={11}/> Add to Plan</>}
              </button>
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ─── Hotel Filter Modal ──────────────────────────────────────────────────────

function HotelFilterModal({ isOpen, onClose, onApply, currentResults, isLoading }) {
  const [numBeds, setNumBeds] = useState(null)
  const [maxPricePerNight, setMaxPricePerNight] = useState(null)
  const [wifiQuality, setWifiQuality] = useState(null)
  const [maxDistance, setMaxDistance] = useState(null)
  const [privateWashroom, setPrivateWashroom] = useState(false)

  const prices = (currentResults?.results || []).map(h => h.price_per_night_usd).filter(Boolean)
  const priceCeil = prices.length ? Math.ceil(Math.max(...prices) * 1.5 / 50) * 50 : 1000
  const priceFloor = 20
  const effectiveMaxPrice = maxPricePerNight ?? priceCeil
  const effectiveMaxDist = maxDistance ?? 20
  const distanceCeil = 20

  if (!isOpen) return null

  const handleApply = () => {
    const filters = {}
    if (numBeds !== null) filters.num_beds = numBeds
    if (maxPricePerNight !== null) filters.max_price_per_night_usd = maxPricePerNight
    if (wifiQuality !== null) filters.wifi_quality = wifiQuality
    if (maxDistance !== null) filters.max_distance_from_center_km = maxDistance
    if (privateWashroom) filters.private_washroom = true
    onApply(filters)
  }

  const handleReset = () => {
    setNumBeds(null)
    setMaxPricePerNight(null)
    setWifiQuality(null)
    setMaxDistance(null)
    setPrivateWashroom(false)
  }

  const hasFilters = numBeds !== null || maxPricePerNight !== null || wifiQuality !== null || maxDistance !== null || privateWashroom
  const activeCount = (numBeds !== null ? 1 : 0) + (maxPricePerNight !== null ? 1 : 0) + (wifiQuality !== null ? 1 : 0) + (maxDistance !== null ? 1 : 0) + (privateWashroom ? 1 : 0)

  const bedOptions = [
    { value: null, label: 'Any' },
    { value: 1, label: '1 Bed' },
    { value: 2, label: '2 Beds' },
    { value: 3, label: '3 Beds' },
    { value: 4, label: '4+' },
  ]

  const wifiOptions = [
    { value: null, label: 'Any' },
    { value: 'basic', label: 'Basic' },
    { value: 'good', label: 'Good' },
    { value: 'excellent', label: 'Excellent' },
  ]

  const sliderThumb = '[&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-4 [&::-webkit-slider-thumb]:h-4 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-violet-500 [&::-webkit-slider-thumb]:cursor-pointer [&::-webkit-slider-thumb]:shadow-md [&::-webkit-slider-thumb]:border-2 [&::-webkit-slider-thumb]:border-white'

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm" onClick={onClose}>
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md mx-4 overflow-hidden animate-in" onClick={e => e.stopPropagation()}>
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100 bg-gradient-to-r from-violet-50 to-white">
          <h3 className="font-bold text-lg text-gray-800 flex items-center gap-2">
            <SlidersHorizontal size={18} className="text-violet-500" /> Hotel Filters
          </h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 transition-colors"><X size={18} /></button>
        </div>

        <div className="px-6 py-5 space-y-6 max-h-[65vh] overflow-y-auto">
          {/* Number of Beds */}
          <div>
            <label className="block text-sm font-semibold text-gray-700 mb-2">Number of Beds</label>
            <div className="grid grid-cols-5 gap-2">
              {bedOptions.map(opt => (
                <button key={String(opt.value)} type="button" onClick={() => setNumBeds(opt.value)}
                  className={`px-3 py-2 rounded-lg text-sm font-medium border-2 transition-all ${numBeds === opt.value ? 'bg-violet-500 border-violet-500 text-white shadow-sm' : 'bg-white border-gray-200 text-gray-600 hover:border-violet-300 hover:text-violet-600'}`}>
                  {opt.label}
                </button>
              ))}
            </div>
          </div>

          {/* Max Price per Night */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="text-sm font-semibold text-gray-700">Max Cost per Night</label>
              <span className="text-sm font-bold text-violet-600">{maxPricePerNight !== null ? `$${effectiveMaxPrice.toLocaleString()}` : 'Any'}</span>
            </div>
            <input
              type="range"
              min={priceFloor} max={priceCeil} step={10}
              value={effectiveMaxPrice}
              onChange={e => setMaxPricePerNight(Number(e.target.value))}
              className={`w-full h-2 bg-gray-200 rounded-full appearance-none cursor-pointer accent-violet-500 ${sliderThumb}`}
            />
            <div className="flex justify-between text-xs text-gray-400 mt-1">
              <span>${priceFloor}</span>
              <span>${priceCeil.toLocaleString()}</span>
            </div>
          </div>

          {/* WiFi Quality */}
          <div>
            <label className="block text-sm font-semibold text-gray-700 mb-2 flex items-center gap-1.5"><Wifi size={14} /> WiFi Quality</label>
            <div className="grid grid-cols-4 gap-2">
              {wifiOptions.map(opt => (
                <button key={String(opt.value)} type="button" onClick={() => setWifiQuality(opt.value)}
                  className={`px-3 py-2 rounded-lg text-sm font-medium border-2 transition-all ${wifiQuality === opt.value ? 'bg-violet-500 border-violet-500 text-white shadow-sm' : 'bg-white border-gray-200 text-gray-600 hover:border-violet-300 hover:text-violet-600'}`}>
                  {opt.label}
                </button>
              ))}
            </div>
          </div>

          {/* Distance from City Center */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="text-sm font-semibold text-gray-700 flex items-center gap-1.5"><MapPin size={14} /> Distance from Center</label>
              <span className="text-sm font-bold text-violet-600">{maxDistance !== null ? `${effectiveMaxDist} km` : 'Any'}</span>
            </div>
            <input
              type="range"
              min={0.5} max={distanceCeil} step={0.5}
              value={effectiveMaxDist}
              onChange={e => setMaxDistance(Number(e.target.value))}
              className={`w-full h-2 bg-gray-200 rounded-full appearance-none cursor-pointer accent-violet-500 ${sliderThumb}`}
            />
            <div className="flex justify-between text-xs text-gray-400 mt-1">
              <span>0.5 km</span>
              <span>{distanceCeil} km</span>
            </div>
          </div>

          {/* Private Washroom */}
          <div>
            <label className="flex items-center gap-3 cursor-pointer group" onClick={() => setPrivateWashroom(v => !v)}>
              <div className={`w-10 h-6 rounded-full transition-all relative ${privateWashroom ? 'bg-violet-500' : 'bg-gray-300'}`}>
                <div className={`absolute top-0.5 w-5 h-5 bg-white rounded-full shadow-md transition-all ${privateWashroom ? 'left-[18px]' : 'left-0.5'}`} />
              </div>
              <div className="flex items-center gap-1.5">
                <Bath size={14} className={privateWashroom ? 'text-violet-600' : 'text-gray-400'} />
                <span className="text-sm font-semibold text-gray-700">Private Washroom</span>
              </div>
              {privateWashroom && <span className="text-xs text-violet-500 font-medium ml-auto">Required</span>}
            </label>
          </div>
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-gray-100 bg-gray-50 flex items-center justify-between">
          <button onClick={handleReset} disabled={!hasFilters}
            className={`text-sm font-medium transition-colors ${hasFilters ? 'text-gray-600 hover:text-red-600' : 'text-gray-300 cursor-default'}`}>
            Reset All
          </button>
          <button onClick={handleApply} disabled={isLoading}
            className="flex items-center gap-2 px-5 py-2.5 bg-violet-500 text-white text-sm font-semibold rounded-xl hover:bg-violet-600 disabled:opacity-60 transition-all shadow-md">
            {isLoading ? <><Loader2 size={14} className="animate-spin" /> Searching...</> : <><SlidersHorizontal size={14} /> Apply Filters{activeCount > 0 ? ` (${activeCount})` : ''}</>}
          </button>
        </div>
      </div>
    </div>
  )
}

function ActivitiesSection({ data, selections, onSelect }) {
  if (!data?.results?.length) return <div className="p-4 text-sm text-gray-500">No activities found</div>
  const catColors = { food:'bg-orange-100 text-orange-700',history:'bg-amber-100 text-amber-700',adventure:'bg-red-100 text-red-700',culture:'bg-purple-100 text-purple-700',nature:'bg-green-100 text-green-700',shopping:'bg-pink-100 text-pink-700',nightlife:'bg-indigo-100 text-indigo-700',wellness:'bg-teal-100 text-teal-700',art:'bg-violet-100 text-violet-700',family:'bg-blue-100 text-blue-700',general:'bg-gray-100 text-gray-700' }
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4 p-4">
      {data.results.map((a, i) => {
        const isSelected = selections.activities.some(x => x.name === a.name)
        return (
          <div key={i} className={`border rounded-xl p-4 transition-all ${isSelected ? 'border-green-400 ring-2 ring-green-300 bg-green-50' : 'border-gray-200 hover:shadow-md'}`}>
            <div className="flex justify-between items-start mb-2">
              <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${catColors[a.category] || catColors.general}`}>{a.category}</span>
              <div className="flex items-center gap-2">
                {a.similarity_score && <span className="text-xs text-gray-400">{Math.round(a.similarity_score*100)}% match</span>}
                <button type="button" onClick={() => onSelect('activities', a)}
                  className={`flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-semibold transition-all ${isSelected ? 'bg-green-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-green-100 hover:text-green-700'}`}>
                  {isSelected ? <><Check size={11}/> Added</> : <><Plus size={11}/> Add</>}
                </button>
              </div>
            </div>
            <h3 className="font-semibold text-gray-900 mb-1">{a.name}</h3>
            <p className="text-sm text-gray-600 mb-2 line-clamp-2">{a.description}</p>
            <div className="flex items-center gap-3 text-xs text-gray-500">
              {a.duration_hours && <span className="flex items-center gap-1"><Clock size={10} />{a.duration_hours}h</span>}
              {a.price_usd != null && <span className="flex items-center gap-1"><DollarSign size={10} />${a.price_usd}</span>}
              {a.location && <span className="flex items-center gap-1"><MapPin size={10} />{a.location}</span>}
              {a.rating && <span className="flex items-center gap-1"><Star size={10} className="text-yellow-400 fill-yellow-400" />{a.rating}{a.review_count ? ` (${a.review_count.toLocaleString()})` : ''}</span>}
            </div>
            <div className="flex items-center gap-2 mt-1.5">
              {a.booking_url && <a href={a.booking_url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 text-xs text-green-600 hover:text-green-800 font-medium"><ExternalLink size={10} /> Book Now</a>}
              {a.source && <span className="px-1.5 py-0.5 rounded text-xs bg-emerald-50 text-emerald-500 border border-emerald-200">{a.source}</span>}
            </div>
          </div>
        )
      })}
    </div>
  )
}

function PlacesToSeeSection({ data, selections, onSelect }) {
  if (!data?.results?.length) return <div className="p-4 text-sm text-gray-500">No places found</div>
  const catColors = { Landmark:'bg-lime-100 text-lime-700', 'Temple/Mosque/Church':'bg-violet-100 text-violet-700', Museum:'bg-sky-100 text-sky-700', Viewpoint:'bg-cyan-100 text-cyan-700', 'Park/Garden':'bg-green-100 text-green-700', Market:'bg-orange-100 text-orange-700', 'Palace/Castle':'bg-amber-100 text-amber-700', 'Natural Wonder':'bg-teal-100 text-teal-700', 'Historic District':'bg-rose-100 text-rose-700', Monument:'bg-gray-100 text-gray-700' }
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4 p-4">
      {data.results.map((place, i) => {
        const isSelected = (selections.places_to_see || []).some(p => p.name === place.name)
        return (
          <div key={i}
            onClick={() => onSelect('places_to_see', place)}
            className={`border rounded-xl p-4 cursor-pointer transition-all ${isSelected ? 'border-lime-400 ring-2 ring-lime-300 bg-lime-50' : 'border-gray-200 hover:shadow-md'}`}
          >
            <div className="flex items-start justify-between mb-2">
              <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${catColors[place.category] || catColors.Landmark}`}>
                {place.category || 'Landmark'}
              </span>
              <div className="flex items-center gap-2">
                {place.rating != null && (
                  <span className="text-xs text-amber-600 font-semibold flex items-center gap-0.5">
                    <Star size={10} className="fill-amber-400 text-amber-400" />
                    {place.rating.toFixed(1)}
                    {place.review_count ? <span className="text-gray-400 font-normal ml-0.5">({place.review_count.toLocaleString()})</span> : null}
                  </span>
                )}
                <button type="button" onClick={e => { e.stopPropagation(); onSelect('places_to_see', place) }}
                  className={`flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-semibold transition-all ${isSelected ? 'bg-lime-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-lime-100 hover:text-lime-700'}`}>
                  {isSelected ? <><Check size={11}/> Added</> : <><Plus size={11}/> Add</>}
                </button>
              </div>
            </div>
            <h3 className="font-semibold text-gray-900 mb-1">{place.name}</h3>
            {(place.neighbourhood || place.address) && (
              <p className="text-xs text-gray-500 mb-1.5 flex items-center gap-1">
                <MapPin size={10} />{place.neighbourhood || place.address}
              </p>
            )}
            <p className="text-sm text-gray-600 mb-2 line-clamp-2">{place.description}</p>
            <div className="flex flex-wrap items-center gap-3 text-xs text-gray-500 mb-2">
              {place.visit_duration_hours && <span className="flex items-center gap-1"><Clock size={10} />~{place.visit_duration_hours}h</span>}
              {place.best_time_to_visit && <span className="flex items-center gap-1"><Info size={10} />{place.best_time_to_visit}</span>}
              {place.admission_fee_usd === 0
                ? <span className="text-green-600 font-medium">Free entry</span>
                : place.admission_fee_usd
                ? <span className="flex items-center gap-1"><DollarSign size={10} />~${place.admission_fee_usd}</span>
                : null}
            </div>
            {place.highlights?.length > 0 && (
              <div className="flex flex-wrap gap-1 mb-2">
                {place.highlights.map((h, j) => (
                  <span key={j} className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded-full">{h}</span>
                ))}
              </div>
            )}
            {place.info_url && (
              <a href={place.info_url} target="_blank" rel="noopener noreferrer"
                onClick={e => e.stopPropagation()}
                className="flex items-center gap-1 text-xs text-lime-600 hover:text-lime-700 font-medium">
                <ExternalLink size={10} /> View details
              </a>
            )}
          </div>
        )
      })}
    </div>
  )
}

// ─── Activity Filter Modal ───────────────────────────────────────────────────

const ACTIVITY_INTERESTS = [
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

function ActivityFilterModal({ isOpen, onClose, onApply, currentResults, isLoading, searchData }) {
  const [selectedInterests, setSelectedInterests] = useState([])
  const [maxPrice, setMaxPrice] = useState(null)
  const [availFrom, setAvailFrom] = useState('')
  const [availTo, setAvailTo] = useState('')
  const [minRating, setMinRating] = useState(null)

  const prices = (currentResults?.results || []).map(a => a.price_usd).filter(Boolean)
  const priceCeil = prices.length ? Math.ceil(Math.max(...prices) * 1.5 / 10) * 10 : 500
  const priceFloor = 0
  const effectiveMaxPrice = maxPrice ?? priceCeil

  const defaultFrom = searchData?.departure_date || ''
  const defaultTo = searchData?.return_date || ''

  if (!isOpen) return null

  const toggleInterest = (id) =>
    setSelectedInterests(prev => prev.includes(id) ? prev.filter(i => i !== id) : [...prev, id])

  const handleApply = () => {
    const filters = {}
    if (selectedInterests.length > 0) filters.filter_interests = selectedInterests
    if (maxPrice !== null) filters.max_price_usd = maxPrice
    if (availFrom) filters.available_from = availFrom
    if (availTo) filters.available_to = availTo
    if (minRating !== null) filters.min_rating = minRating
    onApply(filters)
  }

  const handleReset = () => {
    setSelectedInterests([])
    setMaxPrice(null)
    setAvailFrom('')
    setAvailTo('')
    setMinRating(null)
  }

  const hasFilters = selectedInterests.length > 0 || maxPrice !== null || availFrom || availTo || minRating !== null
  const activeCount = (selectedInterests.length > 0 ? 1 : 0) + (maxPrice !== null ? 1 : 0) + (availFrom || availTo ? 1 : 0) + (minRating !== null ? 1 : 0)

  const sliderThumb = '[&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-4 [&::-webkit-slider-thumb]:h-4 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-emerald-500 [&::-webkit-slider-thumb]:cursor-pointer [&::-webkit-slider-thumb]:shadow-md [&::-webkit-slider-thumb]:border-2 [&::-webkit-slider-thumb]:border-white'

  const ratingOptions = [
    { value: null, label: 'Any' },
    { value: 3, label: '3+' },
    { value: 3.5, label: '3.5+' },
    { value: 4, label: '4+' },
    { value: 4.5, label: '4.5+' },
  ]

  const inputClass = "w-full px-3 py-2 border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-400 text-sm bg-white"

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm" onClick={onClose}>
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md mx-4 overflow-hidden animate-in" onClick={e => e.stopPropagation()}>
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100 bg-gradient-to-r from-emerald-50 to-white">
          <h3 className="font-bold text-lg text-gray-800 flex items-center gap-2">
            <SlidersHorizontal size={18} className="text-emerald-500" /> Activity Filters
          </h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 transition-colors"><X size={18} /></button>
        </div>

        <div className="px-6 py-5 space-y-6 max-h-[65vh] overflow-y-auto">
          {/* Interests */}
          <div>
            <label className="block text-sm font-semibold text-gray-700 mb-2">Interests</label>
            <div className="flex flex-wrap gap-2">
              {ACTIVITY_INTERESTS.map(({ id, label }) => (
                <button key={id} type="button" onClick={() => toggleInterest(id)}
                  className={`px-3 py-1.5 rounded-full text-sm font-medium border-2 transition-all ${selectedInterests.includes(id) ? 'bg-emerald-500 border-emerald-500 text-white shadow-sm' : 'bg-white border-gray-200 text-gray-600 hover:border-emerald-300 hover:text-emerald-600'}`}>
                  {label}
                </button>
              ))}
            </div>
          </div>

          {/* Max Price */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="text-sm font-semibold text-gray-700">Max Cost (per person)</label>
              <span className="text-sm font-bold text-emerald-600">{maxPrice !== null ? `$${effectiveMaxPrice.toLocaleString()}` : 'Any'}</span>
            </div>
            <input
              type="range"
              min={priceFloor} max={priceCeil} step={5}
              value={effectiveMaxPrice}
              onChange={e => setMaxPrice(Number(e.target.value))}
              className={`w-full h-2 bg-gray-200 rounded-full appearance-none cursor-pointer accent-emerald-500 ${sliderThumb}`}
            />
            <div className="flex justify-between text-xs text-gray-400 mt-1">
              <span>$0</span>
              <span>${priceCeil.toLocaleString()}</span>
            </div>
          </div>

          {/* Availability Dates */}
          <div>
            <label className="block text-sm font-semibold text-gray-700 mb-2 flex items-center gap-1.5"><Calendar size={14} /> Availability Dates</label>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs text-gray-500 mb-1">From</label>
                <input type="date" value={availFrom || defaultFrom}
                  onChange={e => setAvailFrom(e.target.value)}
                  className={inputClass} />
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">To</label>
                <input type="date" value={availTo || defaultTo} min={availFrom || defaultFrom}
                  onChange={e => setAvailTo(e.target.value)}
                  className={inputClass} />
              </div>
            </div>
          </div>

          {/* Star Rating */}
          <div>
            <label className="block text-sm font-semibold text-gray-700 mb-2 flex items-center gap-1.5"><Star size={14} className="text-yellow-400 fill-yellow-400" /> Minimum Rating</label>
            <div className="grid grid-cols-5 gap-2">
              {ratingOptions.map(opt => (
                <button key={String(opt.value)} type="button" onClick={() => setMinRating(opt.value)}
                  className={`px-3 py-2 rounded-lg text-sm font-medium border-2 transition-all ${minRating === opt.value ? 'bg-emerald-500 border-emerald-500 text-white shadow-sm' : 'bg-white border-gray-200 text-gray-600 hover:border-emerald-300 hover:text-emerald-600'}`}>
                  {opt.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-gray-100 bg-gray-50 flex items-center justify-between">
          <button onClick={handleReset} disabled={!hasFilters}
            className={`text-sm font-medium transition-colors ${hasFilters ? 'text-gray-600 hover:text-red-600' : 'text-gray-300 cursor-default'}`}>
            Reset All
          </button>
          <button onClick={handleApply} disabled={isLoading}
            className="flex items-center gap-2 px-5 py-2.5 bg-emerald-500 text-white text-sm font-semibold rounded-xl hover:bg-emerald-600 disabled:opacity-60 transition-all shadow-md">
            {isLoading ? <><Loader2 size={14} className="animate-spin" /> Searching...</> : <><SlidersHorizontal size={14} /> Apply Filters{activeCount > 0 ? ` (${activeCount})` : ''}</>}
          </button>
        </div>
      </div>
    </div>
  )
}

function VisaSection({ data }) {
  const req = data?.requirement
  const vacc = data?.vaccinations
  const customs = data?.customs
  if (!req && !vacc && !customs) return <div className="p-4 text-sm text-gray-500">No visa information available</div>
  const typeColors = { 'visa-free':'bg-green-100 text-green-800 border-green-200','visa-on-arrival':'bg-blue-100 text-blue-800 border-blue-200','e-visa':'bg-yellow-100 text-yellow-800 border-yellow-200','visa-required':'bg-red-100 text-red-800 border-red-200' }
  return (
    <div className="p-4 space-y-5">
      {/* Visa Requirements */}
      {req && (
        <div className="space-y-3">
          <div className="flex items-center gap-3">
            <span className={`px-4 py-1.5 rounded-full text-sm font-bold border ${typeColors[req.visa_type] || 'bg-gray-100 text-gray-700 border-gray-200'}`}>{req.visa_type?.replace(/-/g,' ').toUpperCase() || 'UNKNOWN'}</span>
            {req.confidence && <span className="text-xs text-gray-500">Confidence: {req.confidence}</span>}
          </div>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
            {req.max_stay_days && <div className="bg-gray-50 rounded-lg p-3"><p className="text-xs text-gray-500 mb-1">Max Stay</p><p className="font-semibold">{req.max_stay_days} days</p></div>}
            {req.processing_time && <div className="bg-gray-50 rounded-lg p-3"><p className="text-xs text-gray-500 mb-1">Processing</p><p className="font-semibold text-sm">{req.processing_time}</p></div>}
            {req.fee_usd != null && <div className="bg-gray-50 rounded-lg p-3"><p className="text-xs text-gray-500 mb-1">Fee</p><p className="font-semibold">{req.fee_usd === 0 ? 'Free' : `$${req.fee_usd}`}</p></div>}
          </div>
          {req.requirements?.length > 0 && <ul className="space-y-1">{req.requirements.map((r,i) => <li key={i} className="flex items-start gap-2 text-sm text-gray-600"><CheckCircle2 size={13} className="text-green-500 mt-0.5 shrink-0" />{r}</li>)}</ul>}
          {req.notes && <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 text-sm text-blue-800"><Info size={13} className="inline mr-1.5" />{req.notes}</div>}
          {req.official_url && <a href={req.official_url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1.5 text-sm text-orange-600 hover:text-orange-800 font-medium"><ExternalLink size={13} /> Official Source</a>}
        </div>
      )}

      {/* Vaccinations */}
      {vacc && (
        <div className="border-t border-gray-200 pt-4 space-y-3">
          <h3 className="text-sm font-bold text-gray-800 flex items-center gap-1.5"><AlertTriangle size={14} className="text-amber-500" /> Vaccination & Health</h3>
          {vacc.required?.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-red-600 uppercase tracking-wide mb-1">Required</p>
              <ul className="space-y-1">{vacc.required.map((v,i) => <li key={i} className="flex items-start gap-2 text-sm text-gray-700"><AlertCircle size={12} className="text-red-500 mt-0.5 shrink-0" />{v}</li>)}</ul>
            </div>
          )}
          {vacc.recommended?.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-amber-600 uppercase tracking-wide mb-1">Recommended</p>
              <ul className="space-y-1">{vacc.recommended.map((v,i) => <li key={i} className="flex items-start gap-2 text-sm text-gray-700"><CheckCircle2 size={12} className="text-amber-500 mt-0.5 shrink-0" />{v}</li>)}</ul>
            </div>
          )}
          {vacc.covid_status && <div className="bg-green-50 border border-green-200 rounded-lg p-2.5 text-sm text-green-800"><Info size={12} className="inline mr-1" />{vacc.covid_status}</div>}
          {vacc.notes && <p className="text-xs text-gray-500">{vacc.notes}</p>}
          {vacc.source_url && <a href={vacc.source_url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 text-xs text-teal-600 hover:text-teal-800 font-medium"><ExternalLink size={10} /> Health Source</a>}
        </div>
      )}

      {/* Customs */}
      {customs && (
        <div className="border-t border-gray-200 pt-4 space-y-3">
          <h3 className="text-sm font-bold text-gray-800 flex items-center gap-1.5"><Shield size={14} className="text-orange-500" /> Customs & Import Regulations</h3>
          {customs.duty_free_allowances && (
            <div>
              <p className="text-xs font-semibold text-gray-600 uppercase tracking-wide mb-1">Duty-Free Allowances</p>
              <div className="grid grid-cols-2 gap-2">
                {Object.entries(customs.duty_free_allowances).map(([k,v]) => (
                  <div key={k} className="bg-gray-50 rounded-lg p-2.5">
                    <p className="text-xs text-gray-500 capitalize">{k.replace(/_/g, ' ')}</p>
                    <p className="text-sm font-medium text-gray-800">{v}</p>
                  </div>
                ))}
              </div>
            </div>
          )}
          {customs.prohibited_items?.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-red-600 uppercase tracking-wide mb-1">Prohibited Items</p>
              <div className="flex flex-wrap gap-1.5">{customs.prohibited_items.map((item,i) => <span key={i} className="px-2 py-1 bg-red-50 border border-red-200 rounded-full text-xs text-red-700">{item}</span>)}</div>
            </div>
          )}
          {customs.declaration_required?.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-amber-600 uppercase tracking-wide mb-1">Must Declare</p>
              <ul className="space-y-1">{customs.declaration_required.map((d,i) => <li key={i} className="flex items-start gap-2 text-sm text-gray-600"><AlertTriangle size={12} className="text-amber-500 mt-0.5 shrink-0" />{d}</li>)}</ul>
            </div>
          )}
          {customs.notes && <div className="bg-amber-50 border border-amber-200 rounded-lg p-2.5 text-sm text-amber-800"><Info size={12} className="inline mr-1" />{customs.notes}</div>}
          {customs.source_url && <a href={customs.source_url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 text-xs text-teal-600 hover:text-teal-800 font-medium"><ExternalLink size={10} /> Customs Source</a>}
        </div>
      )}
    </div>
  )
}

function SimSection({ data, selections, onSelect }) {
  if (!data?.plans?.length) return <div className="p-4 text-sm text-gray-500">No SIM plans found</div>
  const selected = selections.sim
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 p-4">
      {data.plans.map((p, i) => {
        const isSelected = selected && selected.provider === p.provider && selected.plan_name === p.plan_name
        return (
          <div key={i} className={`border rounded-xl p-4 transition-all ${isSelected ? 'border-pink-400 ring-2 ring-pink-300 bg-pink-50' : 'border-gray-200 hover:shadow-md'}`}>
            <div className="flex justify-between items-start mb-1">
              <h3 className="font-semibold text-gray-900 text-sm">{p.provider}</h3>
              <span className="font-bold text-pink-700">${p.price_usd}</span>
            </div>
            <p className="text-xs text-gray-500 mb-3">{p.plan_name}</p>
            <div className="space-y-1 text-xs text-gray-600 mb-3">
              {p.data_gb ? <div className="flex items-center gap-1.5"><Zap size={10} className="text-pink-400" />{p.data_gb}GB data</div> : <div className="flex items-center gap-1.5"><Zap size={10} className="text-pink-400" />Unlimited data</div>}
              {p.validity_days && <div className="flex items-center gap-1.5"><Clock size={10} className="text-pink-400" />{p.validity_days} days validity</div>}
              {p.network_quality && (
                <div className="flex items-center gap-1.5"><Wifi size={10} className="text-pink-400" />{p.network_quality.speed}{p.network_quality.coverage_rating && <span className={`ml-1 px-1.5 py-0.5 rounded-full text-[10px] font-medium ${p.network_quality.coverage_rating === 'excellent' ? 'bg-green-100 text-green-700' : p.network_quality.coverage_rating === 'good' ? 'bg-blue-100 text-blue-700' : p.network_quality.coverage_rating === 'moderate' ? 'bg-yellow-100 text-yellow-700' : 'bg-red-100 text-red-700'}`}>{p.network_quality.coverage_rating}</span>}</div>
              )}
              {p.network_quality?.coverage_description && <p className="text-[11px] text-gray-400 leading-snug pl-4">{p.network_quality.coverage_description}</p>}
            </div>
            <div className="flex items-center justify-between">
              {p.url
                ? <a href={p.url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 text-xs text-pink-600 hover:text-pink-800 font-medium"><ExternalLink size={10} /> Get Plan</a>
                : <span />}
              <button type="button" onClick={() => onSelect('sim', isSelected ? null : p)}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold transition-all ${isSelected ? 'bg-pink-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-pink-100 hover:text-pink-700'}`}>
                {isSelected ? <><Check size={11}/> Added to Plan</> : <><Plus size={11}/> Add to Plan</>}
              </button>
            </div>
          </div>
        )
      })}
    </div>
  )
}

function TipsSection({ data, selections, onSelect }) {
  if (!data?.tips?.length) return <div className="p-4 text-sm text-gray-500">No tips available</div>
  const sc = { danger:{ icon:AlertCircle, bg:'bg-red-50', border:'border-red-200', text:'text-red-800', ic:'text-red-500', badge:'bg-red-100 text-red-700' }, warning:{ icon:AlertTriangle, bg:'bg-yellow-50', border:'border-yellow-200', text:'text-yellow-800', ic:'text-yellow-500', badge:'bg-yellow-100 text-yellow-700' }, info:{ icon:Info, bg:'bg-blue-50', border:'border-blue-200', text:'text-blue-800', ic:'text-blue-400', badge:'bg-blue-100 text-blue-700' } }
  const selectedTips = selections?.tips || []
  return (
    <div className="p-4 space-y-2">
      {data.tips.map((tip, i) => { const c = sc[tip.severity] || sc.info; const SI = c.icon; const isSelected = selectedTips.some(t => t.title === tip.title); return (
        <div key={i} className={`flex gap-3 p-3 rounded-lg border ${isSelected ? 'border-amber-400 ring-1 ring-amber-300' : ''} ${c.bg} ${c.border}`}>
          <SI size={15} className={`shrink-0 mt-0.5 ${c.ic}`} />
          <div className="flex-1"><div className="flex items-center gap-2 mb-0.5"><span className="text-sm font-semibold text-gray-900">{tip.title}</span><span className={`text-xs px-1.5 py-0.5 rounded-full font-medium ${c.badge}`}>{tip.category}</span></div><p className={`text-sm ${c.text}`}>{tip.body}</p>
          <div className="flex items-center gap-3 mt-1.5">
            {tip.source_url && (
              <a href={tip.source_url} target="_blank" rel="noopener noreferrer"
                 className="flex items-center gap-1 text-xs text-teal-600 hover:text-teal-800 font-medium">
                <ExternalLink size={10} /> Source
              </a>
            )}
            <button type="button" onClick={() => onSelect('tips', tip)}
              className={`flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-semibold transition-all ${isSelected ? 'bg-amber-500 text-white' : 'bg-white/70 text-gray-500 hover:bg-amber-100 hover:text-amber-700 border border-gray-200'}`}>
              {isSelected ? <><Check size={10}/> In Plan</> : <><Plus size={10}/> Add to Plan</>}
            </button>
          </div>
          </div>
        </div>
      )})}
    </div>
  )
}

function GettingAroundSection({ data, selections, onSelect }) {
  if (!data?.options?.length) return <div className="p-4 text-sm text-gray-500">No transportation info available</div>
  const scopeColors = { intra_city: 'bg-cyan-100 text-cyan-700', inter_city: 'bg-indigo-100 text-indigo-700' }
  const typeIcons = { metro: 'M', bus: 'B', tram: 'T', taxi: 'TX', rideshare: 'R', bike: 'BK', scooter: 'SC', walking: 'W', water_transport: 'WT', tourist_transport: 'TT', train: 'TR', long_distance_bus: 'LB', domestic_flight: 'DF', car_rental: 'CR', ferry: 'FY' }
  const selectedTransport = selections?.getting_around || []

  const intraCity = data.options.filter(o => o.scope === 'intra_city')
  const interCity = data.options.filter(o => o.scope === 'inter_city')
  const other = data.options.filter(o => o.scope !== 'intra_city' && o.scope !== 'inter_city')

  const renderGroup = (title, options) => {
    if (!options.length) return null
    return (
      <div className="space-y-3">
        <h3 className="text-sm font-bold text-gray-700 uppercase tracking-wide">{title}</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {options.map((opt, i) => {
            const isSelected = selectedTransport.some(a => a.name === opt.name)
            return (
            <div key={i} className={`border rounded-xl p-4 transition-all ${isSelected ? 'border-cyan-400 ring-2 ring-cyan-300 bg-cyan-50' : 'border-gray-200 hover:shadow-md'}`}>
              <div className="flex items-start justify-between mb-2">
                <div className="flex items-center gap-2">
                  <span className="w-8 h-8 rounded-lg bg-cyan-100 text-cyan-700 flex items-center justify-center text-xs font-bold shrink-0">{typeIcons[opt.type] || '?'}</span>
                  <div>
                    <h4 className="font-semibold text-gray-900 text-sm">{opt.name}</h4>
                    <span className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-medium mt-0.5 ${scopeColors[opt.scope] || 'bg-gray-100 text-gray-600'}`}>{opt.type?.replace(/_/g, ' ')}</span>
                  </div>
                </div>
                <button type="button" onClick={() => onSelect('getting_around', opt)}
                  className={`flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-semibold transition-all ${isSelected ? 'bg-cyan-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-cyan-100 hover:text-cyan-700'}`}>
                  {isSelected ? <><Check size={11}/> Added</> : <><Plus size={11}/> Add</>}
                </button>
              </div>
              {opt.description && <p className="text-sm text-gray-600 mb-2">{opt.description}</p>}
              {opt.coverage && <p className="text-sm text-gray-500 mb-1"><span className="font-medium">Coverage:</span> {opt.coverage}</p>}
              {opt.price_info && <p className="text-sm text-gray-500 mb-1"><span className="font-medium">Price:</span> {opt.price_info}</p>}
              {opt.operating_hours && <p className="text-sm text-gray-500 mb-1"><span className="font-medium">Hours:</span> {opt.operating_hours}</p>}
              {opt.tourist_pass && <p className="text-sm text-cyan-600 mb-1"><span className="font-medium">Tourist Pass:</span> {opt.tourist_pass}</p>}
              {opt.tips && <p className="text-sm text-gray-500 italic mt-1">{opt.tips}</p>}
              {opt.booking_url && (
                <a href={opt.booking_url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 text-xs text-cyan-600 hover:text-cyan-800 font-medium mt-2"><ExternalLink size={10} /> More Info</a>
              )}
            </div>
            )
          })}
        </div>
      </div>
    )
  }

  return (
    <div className="p-4 space-y-5">
      {renderGroup('In the City', intraCity)}
      {renderGroup('Between Cities', interCity)}
      {renderGroup('Other', other)}
    </div>
  )
}

function ForexSection({ data }) {
  if (!data || data.error) return <div className="p-4 text-sm text-gray-500">No currency information available</div>
  const ratingColors = { excellent: 'bg-emerald-100 text-emerald-700', good: 'bg-blue-100 text-blue-700', fair: 'bg-yellow-100 text-yellow-700', poor: 'bg-red-100 text-red-700' }
  const locTypeIcons = { atm: '🏧', bank: '🏦', exchange_bureau: '💱', hotel: '🏨', airport: '✈️', online: '🌐' }
  const isHome = (rate) => rate.from_currency !== 'USD' && rate.from_currency !== 'EUR'

  return (
    <div className="p-4 space-y-5">
      {/* Currency & Exchange Rates */}
      {data?.local_currency && (
        <div className="bg-gradient-to-r from-emerald-50 to-green-50 border border-emerald-200 rounded-xl p-4">
          <h3 className="text-sm font-bold text-emerald-800 mb-2 flex items-center gap-2">
            <DollarSign size={16} /> {data.local_currency.name} ({data.local_currency.code}) {data.local_currency.symbol}
          </h3>
          {data.exchange_rates?.length > 0 && (
            <div className={`grid grid-cols-1 ${data.exchange_rates.length >= 3 ? 'md:grid-cols-3' : 'md:grid-cols-2'} gap-3 mt-3`}>
              {data.exchange_rates.map((rate, i) => (
                <div key={i} className={`rounded-lg p-3 border ${isHome(rate) ? 'bg-amber-50 border-amber-200 ring-1 ring-amber-300' : 'bg-white border-emerald-100'}`}>
                  {isHome(rate) && <span className="text-[10px] font-semibold text-amber-600 uppercase tracking-wide">Your Currency</span>}
                  <div className="flex items-baseline gap-2">
                    {rate.rate != null
                      ? <span className={`text-lg font-bold ${isHome(rate) ? 'text-amber-700' : 'text-emerald-700'}`}>{rate.rate}</span>
                      : <span className="flex items-center gap-1 text-sm text-gray-400"><Loader2 size={12} className="animate-spin" /> Fetching live rate...</span>
                    }
                    <span className="text-sm text-gray-500">{rate.description}</span>
                  </div>
                  {rate.trend && rate.trend !== 'Live rate loading...' && <p className="text-xs text-gray-500 mt-1">{rate.trend}</p>}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Exchange Locations */}
      {data?.exchange_locations?.length > 0 && (
        <div>
          <h3 className="text-sm font-bold text-gray-700 uppercase tracking-wide mb-3">Where to Exchange</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {data.exchange_locations.map((loc, i) => (
              <div key={i} className="border border-gray-200 rounded-xl p-4 hover:shadow-md transition-all">
                <div className="flex items-start justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <span className="text-xl">{locTypeIcons[loc.type] || '💰'}</span>
                    <div>
                      <h4 className="font-semibold text-gray-900 text-sm">{loc.name}</h4>
                      {loc.rating && <span className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-medium mt-0.5 ${ratingColors[loc.rating] || 'bg-gray-100 text-gray-600'}`}>{loc.rating}</span>}
                    </div>
                  </div>
                </div>
                {loc.description && <p className="text-sm text-gray-600 mb-2">{loc.description}</p>}
                {loc.fees && <p className="text-sm text-gray-500 mb-1"><span className="font-medium">Fees:</span> {loc.fees}</p>}
                {loc.tip && <p className="text-sm text-emerald-600 italic">{loc.tip}</p>}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Card & Cash Info */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {data?.card_acceptance && (
          <div className="bg-sky-50 border border-sky-200 rounded-xl p-4">
            <h3 className="text-sm font-bold text-sky-800 mb-2">Card Acceptance</h3>
            <div className="space-y-1.5 text-sm">
              {data.card_acceptance.visa_mastercard && <p><span className="font-medium text-gray-700">Visa/MC:</span> {data.card_acceptance.visa_mastercard}</p>}
              {data.card_acceptance.amex && <p><span className="font-medium text-gray-700">Amex:</span> {data.card_acceptance.amex}</p>}
              {data.card_acceptance.contactless && <p><span className="font-medium text-gray-700">Contactless:</span> {data.card_acceptance.contactless}</p>}
              {data.card_acceptance.digital_wallets && <p><span className="font-medium text-gray-700">Digital:</span> {data.card_acceptance.digital_wallets}</p>}
              {data.card_acceptance.surcharges && <p className="text-amber-600"><span className="font-medium">Surcharges:</span> {data.card_acceptance.surcharges}</p>}
            </div>
          </div>
        )}

        {data?.cash_advice && (
          <div className="bg-amber-50 border border-amber-200 rounded-xl p-4">
            <h3 className="text-sm font-bold text-amber-800 mb-2">Cash Advice</h3>
            {data.cash_advice.cash_dependency && (
              <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-semibold mb-2 ${
                data.cash_advice.cash_dependency === 'high' ? 'bg-red-100 text-red-700' :
                data.cash_advice.cash_dependency === 'medium' ? 'bg-yellow-100 text-yellow-700' :
                'bg-green-100 text-green-700'
              }`}>Cash dependency: {data.cash_advice.cash_dependency}</span>
            )}
            <div className="space-y-1.5 text-sm">
              {data.cash_advice.recommendation && <p>{data.cash_advice.recommendation}</p>}
              {data.cash_advice.denominations && <p><span className="font-medium text-gray-700">Denominations:</span> {data.cash_advice.denominations}</p>}
              {data.cash_advice.bring_usd_eur && <p><span className="font-medium text-gray-700">Bring USD/EUR?</span> {data.cash_advice.bring_usd_eur}</p>}
            </div>
          </div>
        )}
      </div>

      {/* ATM Info */}
      {data?.atm_info && (
        <div className="bg-violet-50 border border-violet-200 rounded-xl p-4">
          <h3 className="text-sm font-bold text-violet-800 mb-2">ATM Information</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-1.5 text-sm">
            {data.atm_info.availability && <p><span className="font-medium text-gray-700">Availability:</span> {data.atm_info.availability}</p>}
            {data.atm_info.networks && <p><span className="font-medium text-gray-700">Networks:</span> {data.atm_info.networks}</p>}
            {data.atm_info.withdrawal_limit && <p><span className="font-medium text-gray-700">Limit:</span> {data.atm_info.withdrawal_limit}</p>}
            {data.atm_info.fees && <p><span className="font-medium text-gray-700">Fees:</span> {data.atm_info.fees}</p>}
            {data.atm_info.best_option && <p className="text-emerald-700 font-medium col-span-2">{data.atm_info.best_option}</p>}
          </div>
        </div>
      )}

      {/* Tipping */}
      {data?.tipping && (
        <div className={`rounded-xl p-3 border text-sm ${data.tipping.expected ? 'bg-amber-50 border-amber-200' : 'bg-green-50 border-green-200'}`}>
          <span className="font-semibold">{data.tipping.expected ? '💵 Tipping expected' : '✅ Tipping not expected'}</span>
          {data.tipping.description && <span className="text-gray-600"> — {data.tipping.description}</span>}
        </div>
      )}

      {/* Money Tips */}
      {data?.money_tips?.length > 0 && (
        <div>
          <h3 className="text-sm font-bold text-gray-700 uppercase tracking-wide mb-2">Money Tips</h3>
          <div className="space-y-2">
            {data.money_tips.map((tip, i) => (
              <div key={i} className="flex gap-3 p-3 rounded-lg border border-emerald-200 bg-emerald-50">
                <Lightbulb size={15} className="shrink-0 mt-0.5 text-emerald-500" />
                <div>
                  <p className="text-sm font-semibold text-gray-900">{tip.title}</p>
                  <p className="text-sm text-emerald-800 mt-0.5">{tip.body}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Source URLs */}
      {data?.source_urls?.length > 0 && (
        <div className="flex flex-wrap gap-2 pt-2">
          {data.source_urls.map((url, i) => (
            <a key={i} href={url} target="_blank" rel="noopener noreferrer"
               className="flex items-center gap-1 text-xs text-emerald-600 hover:text-emerald-800 font-medium">
              <ExternalLink size={10} /> Source {i + 1}
            </a>
          ))}
        </div>
      )}
    </div>
  )
}

// Build a client-side fallback itinerary from activities + hotels data
function buildClientItinerary(activities, hotels, searchData) {
  if (!searchData) return null
  const dep = new Date(searchData.departure_date)
  const ret = searchData.return_date ? new Date(searchData.return_date) : null
  const nights = ret ? Math.round((ret - dep) / 86400000) : 7
  const actList = (activities?.results || []).filter(a => !a.error)
  const hotelName = hotels?.results?.[0]?.name || 'your hotel'
  const dest = searchData.destination || 'your destination'

  const themes = [
    'Arrival & First Impressions',
    ...Array.from({ length: Math.max(0, nights - 1) }, (_, i) => `Day ${i + 2} — Exploration`),
    'Departure Day',
  ]

  const days = []
  let actIdx = 0
  let totalCost = 0

  for (let dayNum = 1; dayNum <= nights + 1; dayNum++) {
    const dateStr = new Date(dep.getTime() + (dayNum - 1) * 86400000).toISOString().slice(0, 10)
    const isFirst = dayNum === 1
    const isLast  = dayNum === nights + 1
    const theme   = themes[Math.min(dayNum - 1, themes.length - 1)]

    let slots = []
    if (isFirst) {
      slots = [
        { time_of_day: 'morning',   activity: `Arrive at ${dest}, transfer to ${hotelName}`, location: dest, duration_hours: 3, notes: 'Pick up local transport card at the airport', estimated_cost_usd: 30 },
        { time_of_day: 'afternoon', activity: `Check in to ${hotelName}, freshen up and explore the area`, location: dest, duration_hours: 3, notes: 'Rest after the journey', estimated_cost_usd: 20 },
        { time_of_day: 'evening',   activity: 'Welcome dinner at a local restaurant', location: dest, duration_hours: 2, notes: 'Ask hotel staff for recommendations', estimated_cost_usd: 40 },
      ]
    } else if (isLast) {
      slots = [
        { time_of_day: 'morning',   activity: 'Final breakfast and last-minute shopping', location: dest, duration_hours: 2, notes: 'Pack the evening before', estimated_cost_usd: 25 },
        { time_of_day: 'afternoon', activity: `Check out of ${hotelName} and head to airport`, location: dest, duration_hours: 3, notes: 'Allow extra time for check-in', estimated_cost_usd: 25 },
        { time_of_day: 'evening',   activity: 'Departure flight', location: 'Airport', duration_hours: 3, notes: 'Safe travels!', estimated_cost_usd: 0 },
      ]
    } else {
      slots = ['morning', 'afternoon', 'evening'].map(tod => {
        if (actIdx < actList.length) {
          const a = actList[actIdx++]
          return { time_of_day: tod, activity: a.name || 'Local exploration', location: a.location || dest, duration_hours: a.duration_hours || 2, notes: a.description || '', estimated_cost_usd: Number(a.price_usd) || 25 }
        }
        return { time_of_day: tod, activity: `Free time — explore ${dest}`, location: dest, duration_hours: 3, notes: 'Great for spontaneous discoveries', estimated_cost_usd: 30 }
      })
    }

    const dailyCost = slots.reduce((s, sl) => s + (sl.estimated_cost_usd || 0), 0)
    totalCost += dailyCost
    days.push({ day_number: dayNum, date: dateStr, theme, slots, daily_estimated_cost_usd: dailyCost })
  }

  return { days, total_estimated_cost_usd: Math.round(totalCost), source: 'template' }
}

function ItinerarySection({ data, selections, onNoteChange, onSlotEdit, onSlotPlan }) {
  const [editingSlot, setEditingSlot] = useState(null) // key of slot being edited
  const [openNote,    setOpenNote]    = useState(null)

  if (!data?.days?.length) return <div className="p-4 text-sm text-gray-500">No itinerary available</div>

  const slotIcons = { morning: '🌅', afternoon: '☀️', evening: '🌙' }

  return (
    <div className="p-4 space-y-4">
      {/* Header row */}
      <div className="flex items-center justify-between">
        {data.total_estimated_cost_usd > 0 && (
          <div className="flex items-center gap-2 p-2.5 bg-teal-50 rounded-lg border border-teal-200 text-sm">
            <DollarSign size={13} className="text-teal-600" />
            <span className="text-teal-800 font-medium">Est. itinerary cost: ${data.total_estimated_cost_usd.toLocaleString()}</span>
          </div>
        )}
        {data.source === 'template' && (
          <span className="text-xs text-amber-600 bg-amber-50 border border-amber-200 px-2 py-1 rounded-full">Auto-generated — click any slot to edit</span>
        )}
      </div>

      {data.days.map((day) => (
        <div key={day.day_number} className="border border-gray-200 rounded-xl overflow-hidden">
          {/* Day header */}
          <div className="flex items-center justify-between px-4 py-3 bg-gradient-to-r from-teal-600 to-teal-700 text-white">
            <div>
              <span className="font-bold">Day {day.day_number}</span>
              {day.date && <span className="ml-2 text-teal-200 text-sm">{day.date}</span>}
            </div>
            <div className="text-right">
              {day.theme && <p className="text-sm font-medium">{day.theme}</p>}
              {day.daily_estimated_cost_usd > 0 && <p className="text-xs text-teal-200">${day.daily_estimated_cost_usd} est.</p>}
            </div>
          </div>

          {/* Slots */}
          <div className="divide-y divide-gray-100">
            {day.slots?.map((slot, j) => {
              const key = `${day.day_number}-${slot.time_of_day}`
              const edit  = selections.itinerary_edits?.[key] || {}
              const note  = selections.itinerary_notes?.[key] || ''
              const isEditing  = editingSlot === key
              const isNoteOpen = openNote === key

              // Merge saved edits over original slot data
              const activity = edit.activity  ?? slot.activity
              const location = edit.location  ?? slot.location
              const cost     = edit.cost      ?? slot.estimated_cost_usd

              return (
                <div key={j} className={`px-4 py-3 transition-colors ${isEditing ? 'bg-teal-50' : 'hover:bg-gray-50'}`}>
                  <div className="flex gap-3">
                    {/* Time icon */}
                    <div className="w-20 shrink-0 text-sm text-gray-500 font-medium capitalize flex items-center gap-1">
                      <span>{slotIcons[slot.time_of_day]}</span>
                      <span>{slot.time_of_day}</span>
                    </div>

                    {/* Content — view or edit */}
                    <div className="flex-1 min-w-0">
                      {isEditing ? (
                        <div className="space-y-2">
                          <div>
                            <label className="text-xs text-teal-600 font-medium">Activity</label>
                            <input
                              autoFocus
                              type="text"
                              value={edit.activity ?? slot.activity}
                              onChange={e => onSlotEdit(key, 'activity', e.target.value)}
                              className="mt-0.5 w-full text-sm border border-teal-300 rounded-lg px-2.5 py-1.5 focus:outline-none focus:ring-1 focus:ring-teal-400 bg-white"
                            />
                          </div>
                          <div className="grid grid-cols-2 gap-2">
                            <div>
                              <label className="text-xs text-teal-600 font-medium">Location</label>
                              <input
                                type="text"
                                value={edit.location ?? slot.location ?? ''}
                                onChange={e => onSlotEdit(key, 'location', e.target.value)}
                                className="mt-0.5 w-full text-xs border border-teal-300 rounded-lg px-2.5 py-1.5 focus:outline-none focus:ring-1 focus:ring-teal-400 bg-white"
                              />
                            </div>
                            <div>
                              <label className="text-xs text-teal-600 font-medium">Est. cost ($)</label>
                              <input
                                type="number"
                                value={edit.cost ?? slot.estimated_cost_usd ?? ''}
                                onChange={e => onSlotEdit(key, 'cost', e.target.value === '' ? null : Number(e.target.value))}
                                className="mt-0.5 w-full text-xs border border-teal-300 rounded-lg px-2.5 py-1.5 focus:outline-none focus:ring-1 focus:ring-teal-400 bg-white"
                              />
                            </div>
                          </div>
                          <div>
                            <label className="text-xs text-teal-600 font-medium">Personal note</label>
                            <textarea
                              value={note}
                              onChange={e => onNoteChange(key, e.target.value)}
                              placeholder="Add your note…"
                              className="mt-0.5 w-full text-xs border border-teal-300 rounded-lg px-2.5 py-1.5 focus:outline-none focus:ring-1 focus:ring-teal-400 resize-none bg-white"
                              rows={2}
                            />
                          </div>
                          <button onClick={() => setEditingSlot(null)}
                            className="flex items-center gap-1 px-3 py-1 bg-teal-600 text-white rounded-full text-xs font-semibold hover:bg-teal-700">
                            <Check size={10}/> Done
                          </button>
                        </div>
                      ) : (
                        <>
                          <p className="text-sm font-medium text-gray-900">{activity}</p>
                          {location && <p className="text-sm text-gray-500 mt-0.5 flex items-center gap-1"><MapPin size={11}/>{location}</p>}
                          {slot.notes && !edit.activity && <p className="text-sm text-gray-400 mt-1 italic">{slot.notes}</p>}
                          {note && <p className="text-sm text-teal-600 mt-1 italic">📝 {note}</p>}
                        </>
                      )}
                    </div>

                    {/* Actions */}
                    {!isEditing && (
                      <div className="shrink-0 flex flex-col items-end gap-1.5">
                        {cost != null && <span className="text-sm text-gray-400">${cost}</span>}
                        <button onClick={() => { setEditingSlot(key); setOpenNote(null) }}
                          className={`flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium transition-colors ${(edit.activity || edit.location) ? 'bg-teal-100 text-teal-700' : 'bg-gray-100 text-gray-500 hover:bg-teal-100 hover:text-teal-700'}`}>
                          <PenLine size={10}/> {(edit.activity || edit.location) ? 'Edited' : 'Edit'}
                        </button>
                        {!edit.activity && (
                          <button onClick={() => { setOpenNote(isNoteOpen ? null : key); setEditingSlot(null) }}
                            className={`flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium transition-colors ${note ? 'bg-amber-100 text-amber-700' : 'bg-gray-100 text-gray-500 hover:bg-amber-100 hover:text-amber-700'}`}>
                            <PenLine size={10}/> {note ? 'Note ✓' : 'Note'}
                          </button>
                        )}
                        <button onClick={() => onSlotPlan(key, { key, day_number: day.day_number, time_of_day: slot.time_of_day, activity, location, estimated_cost_usd: cost })}
                          className={`flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium transition-colors ${
                            selections.itinerary_slots?.some(s => s.key === key)
                              ? 'bg-teal-600 text-white'
                              : 'bg-gray-100 text-gray-500 hover:bg-teal-100 hover:text-teal-700'
                          }`}>
                          {selections.itinerary_slots?.some(s => s.key === key)
                            ? <><Check size={10}/> In Plan</>
                            : <><Plus size={10}/> Plan</>
                          }
                        </button>
                      </div>
                    )}
                  </div>

                  {/* Inline note textarea when not in full edit mode */}
                  {isNoteOpen && !isEditing && (
                    <div className="mt-2 ml-23 pl-20">
                      <textarea
                        autoFocus
                        value={note}
                        onChange={e => onNoteChange(key, e.target.value)}
                        placeholder="Add your personal note…"
                        className="w-full text-xs border border-amber-300 rounded-lg px-2.5 py-2 focus:outline-none focus:ring-1 focus:ring-amber-400 resize-none bg-amber-50"
                        rows={2}
                      />
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      ))}
    </div>
  )
}

// ─── Cost estimator ───────────────────────────────────────────────────────────

function computeEstimatedCost(selections, searchData) {
  let total = 0
  if (selections.flight?.price_usd) total += Number(selections.flight.price_usd)
  if (selections.hotel) {
    if (selections.hotel.total_price_usd) {
      total += Number(selections.hotel.total_price_usd)
    } else if (selections.hotel.price_per_night_usd) {
      const nights = searchData?.return_date && searchData?.departure_date
        ? Math.max(1, (new Date(searchData.return_date) - new Date(searchData.departure_date)) / 86400000)
        : 7
      total += Number(selections.hotel.price_per_night_usd) * nights
    }
  }
  selections.activities.forEach(a => { if (a.price_usd) total += Number(a.price_usd) })
  if (selections.sim?.price_usd) total += Number(selections.sim.price_usd)
  return total
}

// ─── My Plan Drawer ───────────────────────────────────────────────────────────

function MyPlanDrawer({ isOpen, onClose, selections, planName, onPlanNameChange, onRemoveSelection, onViewPlan, token, searchData, results, loadedPlanId, onLoadPlan, onClearLoadedPlan, onClearSelections }) {
  const [saving, setSaving]         = useState(false)
  const [saveMsg, setSaveMsg]       = useState('')
  const [savedPlans, setSavedPlans] = useState([])
  const [loadingPlans, setLoadingPlans] = useState(false)
  const [deletingId, setDeletingId] = useState(null)
  const [isDragOver, setIsDragOver] = useState(false)
  const [isDragOverSaved, setIsDragOverSaved] = useState(false)

  const selectedCount = countSelections(selections) + Object.values(selections.itinerary_notes).filter(Boolean).length
  const estimatedCost = computePlanCost(selections, searchData)
  const budget = getBudgetStatus(estimatedCost, searchData?.budget_usd)

  const loadPlans = async () => {
    if (!token) return
    setLoadingPlans(true)
    try {
      const res = await fetch('/api/plans', { headers: { Authorization: `Bearer ${token}` } })
      if (res.ok) setSavedPlans(await res.json())
    } finally { setLoadingPlans(false) }
  }

  useEffect(() => { if (isOpen) loadPlans() }, [isOpen])

  const save = async () => {
    if (!token) { setSaveMsg('Please log in to save plans'); return }
    setSaving(true); setSaveMsg('')
    try {
      const isUpdate = !!loadedPlanId
      const url = isUpdate ? `/api/plans/${loadedPlanId}` : '/api/plans'
      const method = isUpdate ? 'PUT' : 'POST'
      const body = isUpdate
        ? JSON.stringify({ name: planName, selections })
        : JSON.stringify({ name: planName, search_data: searchData, selections })
      const res = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body,
      })
      if (res.ok) {
        setSaveMsg(isUpdate ? 'Plan updated!' : 'Plan saved!')
        track('plan_saved', 'results', { is_update: isUpdate })
        loadPlans(); setTimeout(() => setSaveMsg(''), 3000)
      } else setSaveMsg('Save failed')
    } catch { setSaveMsg('Save failed') }
    finally { setSaving(false) }
  }

  const deletePlan = async (id) => {
    if (!token) return
    setDeletingId(id)
    try {
      await fetch(`/api/plans/${id}`, { method: 'DELETE', headers: { Authorization: `Bearer ${token}` } })
      setSavedPlans(p => p.filter(x => x.id !== id))
    } finally { setDeletingId(null) }
  }

  const saveAndClear = async () => {
    if (!token) { setSaveMsg('Please log in to save plans'); return }
    setSaving(true); setSaveMsg('')
    try {
      const isUpdate = !!loadedPlanId
      const url = isUpdate ? `/api/plans/${loadedPlanId}` : '/api/plans'
      const method = isUpdate ? 'PUT' : 'POST'
      const body = isUpdate
        ? JSON.stringify({ name: planName, selections })
        : JSON.stringify({ name: planName, search_data: searchData, selections })
      const res = await fetch(url, { method, headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` }, body })
      if (res.ok) {
        setSaveMsg(isUpdate ? 'Plan sent back!' : 'Plan saved!')
        loadPlans()
        onClearLoadedPlan()
        onClearSelections()
        onPlanNameChange('My Trip Plan')
        setTimeout(() => setSaveMsg(''), 3000)
      } else setSaveMsg('Save failed')
    } catch { setSaveMsg('Save failed') }
    finally { setSaving(false) }
  }

  const handleCurrentPlanDragStart = (e) => {
    e.dataTransfer.setData('application/x-current-plan', JSON.stringify({ name: planName, selections }))
    e.dataTransfer.effectAllowed = 'move'
  }

  return (
    <>
      {/* Backdrop */}
      {isOpen && <div className="fixed inset-0 bg-black/30 z-40" onClick={onClose} />}

      {/* Drawer */}
      <div className={`fixed top-0 right-0 h-full w-full max-w-sm bg-white shadow-2xl z-50 flex flex-col transform transition-transform duration-300 ${isOpen ? 'translate-x-0' : 'translate-x-full'}`}>
        {/* Header */}
        <div className="px-4 py-3 bg-gradient-to-r from-slate-500 to-slate-600 text-white shrink-0">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Bookmark size={18} />
              <h2 className="font-semibold">My Plan</h2>
              {selectedCount > 0 && <span className="bg-white/30 text-white text-xs font-bold px-2 py-0.5 rounded-full">{selectedCount}</span>}
              {loadedPlanId && <span className="bg-amber-400/30 text-amber-100 text-[10px] font-medium px-1.5 py-0.5 rounded">Editing saved plan</span>}
            </div>
            <div className="flex items-center gap-3">
              {estimatedCost > 0 && (
                <div className="text-right">
                  <p className="font-bold text-sm">${estimatedCost.toLocaleString(undefined, {maximumFractionDigits:0})}</p>
                </div>
              )}
              <button onClick={onClose} className="text-white/80 hover:text-white"><X size={18} /></button>
            </div>
          </div>
          {budget && (
            <div className={`mt-1.5 text-xs font-medium px-2.5 py-1 rounded-md inline-flex items-center gap-1.5 ${budget.status === 'under' ? 'bg-green-500/20 text-green-200' : 'bg-red-500/20 text-red-200'}`}>
              <DollarSign size={11} />
              {budget.label}
              {searchData?.budget_usd && <span className="text-white/50 ml-1">(budget: ${searchData.budget_usd.toLocaleString()})</span>}
            </div>
          )}
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {/* Plan name — draggable handle for sending current plan to saved */}
          <div
            draggable={selectedCount > 0}
            onDragStart={selectedCount > 0 ? handleCurrentPlanDragStart : undefined}
            className={selectedCount > 0 ? 'cursor-grab active:cursor-grabbing' : ''}
          >
            <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">
              Plan Name {selectedCount > 0 && <span className="text-gray-300 font-normal normal-case">· drag to send to saved</span>}
            </label>
            <input type="text" value={planName} onChange={e => onPlanNameChange(e.target.value)}
              className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-400" />
          </div>

          {/* Selected flight */}
          {selections.flight && (
            <div className="border border-sky-200 bg-sky-50 rounded-xl p-3">
              <div className="flex items-center justify-between mb-1">
                <div className="flex items-center gap-1.5 text-xs font-semibold text-sky-700 uppercase tracking-wide"><Plane size={11}/> Flight</div>
                <button onClick={() => onRemoveSelection('flight')} className="text-gray-400 hover:text-red-500"><X size={13}/></button>
              </div>
              {selections.flight.outbound ? (
                <>
                  <p className="text-xs text-gray-500 mb-0.5">Outbound: <span className="font-medium text-gray-700">{selections.flight.outbound.airline}</span>{selections.flight.outbound.flight_number && <span className="text-gray-400 ml-1">{selections.flight.outbound.flight_number}</span>} · {selections.flight.outbound.origin} → {selections.flight.outbound.destination}</p>
                  {selections.flight.return && <p className="text-xs text-gray-500 mb-0.5">Return: <span className="font-medium text-gray-700">{selections.flight.return.airline}</span>{selections.flight.return.flight_number && <span className="text-gray-400 ml-1">{selections.flight.return.flight_number}</span>} · {selections.flight.return.origin} → {selections.flight.return.destination}</p>}
                  <p className="text-xs font-semibold text-sky-700 mt-1">${selections.flight.price_usd?.toLocaleString()} {selections.flight.trip_type === 'round_trip' ? 'round-trip' : 'one-way'}</p>
                </>
              ) : (
                <>
                  <p className="text-sm font-medium">{selections.flight.airline}{selections.flight.flight_number && <span className="text-xs text-gray-400 ml-1">{selections.flight.flight_number}</span>}</p>
                  <p className="text-xs text-gray-500">{selections.flight.origin} → {selections.flight.destination} · ${selections.flight.price_usd?.toLocaleString()}</p>
                </>
              )}
              {selections.flight.booking_url && (
                <a href={selections.flight.booking_url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 text-xs text-sky-600 hover:text-sky-800 font-medium mt-1.5"><ExternalLink size={10} /> Book this flight</a>
              )}
            </div>
          )}

          {/* Selected hotel */}
          {selections.hotel && (
            <div className="border border-purple-200 bg-purple-50 rounded-xl p-3">
              <div className="flex items-center justify-between mb-1">
                <div className="flex items-center gap-1.5 text-xs font-semibold text-purple-700 uppercase tracking-wide"><Hotel size={11}/> Hotel</div>
                <button onClick={() => onRemoveSelection('hotel')} className="text-gray-400 hover:text-red-500"><X size={13}/></button>
              </div>
              <p className="text-sm font-medium">{selections.hotel.name}</p>
              <div className="flex items-center gap-2 mt-0.5">
                {selections.hotel.star_rating > 0 && <div className="flex">{[...Array(Math.round(selections.hotel.star_rating))].map((_, j) => <Star key={j} size={9} className="text-yellow-400 fill-yellow-400" />)}</div>}
                {selections.hotel.review_score && <span className="text-xs text-gray-400">{selections.hotel.review_score}/10</span>}
              </div>
              <p className="text-xs text-gray-500 mt-0.5">{selections.hotel.location} · ${selections.hotel.price_per_night_usd?.toLocaleString()}/night{selections.hotel.total_price_usd ? ` · $${selections.hotel.total_price_usd.toLocaleString()} total` : ''}</p>
              {selections.hotel.booking_url && (
                <a href={selections.hotel.booking_url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 text-xs text-purple-600 hover:text-purple-800 font-medium mt-1.5"><ExternalLink size={10} /> View & Book</a>
              )}
            </div>
          )}

          {/* Selected activities */}
          {selections.activities.length > 0 && (
            <div className="border border-green-200 bg-green-50 rounded-xl p-3">
              <div className="text-xs font-semibold text-green-700 uppercase tracking-wide mb-2 flex items-center gap-1.5"><MapPin size={11}/> Activities ({selections.activities.length})</div>
              <div className="space-y-2">
                {selections.activities.map((a, i) => (
                  <div key={i} className="flex items-start justify-between border-b border-green-100 last:border-0 pb-1.5 last:pb-0">
                    <div className="flex-1 min-w-0 mr-2">
                      <p className="text-xs font-medium text-gray-800">{a.name}</p>
                      <div className="flex items-center gap-2 mt-0.5 text-xs text-gray-500">
                        {a.price_usd != null && <span>${a.price_usd}</span>}
                        {a.duration_hours && <span>{a.duration_hours}h</span>}
                        {a.location && <span className="truncate">{a.location}</span>}
                      </div>
                      {a.booking_url && (
                        <a href={a.booking_url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 text-xs text-green-600 hover:text-green-800 font-medium mt-0.5"><ExternalLink size={9} /> Book</a>
                      )}
                    </div>
                    <button onClick={() => onRemoveSelection('activities', a)} className="text-gray-400 hover:text-red-500 shrink-0 mt-0.5"><X size={12}/></button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Selected places */}
          {(selections.places_to_see?.length > 0) && (
            <div className="border border-lime-200 bg-lime-50 rounded-xl p-3">
              <div className="text-xs font-semibold text-lime-700 uppercase tracking-wide mb-2 flex items-center gap-1.5"><Map size={11}/> Places to See ({selections.places_to_see.length})</div>
              <div className="space-y-2">
                {selections.places_to_see.map((place, i) => (
                  <div key={i} className="flex items-start justify-between border-b border-lime-100 last:border-0 pb-1.5 last:pb-0">
                    <div className="flex-1 min-w-0 mr-2">
                      <p className="text-xs font-medium text-gray-800">{place.name}</p>
                      <div className="flex items-center gap-2 mt-0.5 text-xs text-gray-500">
                        {place.category && <span>{place.category}</span>}
                        {place.neighbourhood && <span className="truncate">{place.neighbourhood}</span>}
                        {place.admission_fee_usd === 0 && <span className="text-green-600">Free</span>}
                      </div>
                      {place.info_url && (
                        <a href={place.info_url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 text-xs text-lime-600 hover:text-lime-800 font-medium mt-0.5"><ExternalLink size={9} /> Details</a>
                      )}
                    </div>
                    <button onClick={() => onRemoveSelection('places_to_see', place)} className="text-gray-400 hover:text-red-500 shrink-0 mt-0.5"><X size={12}/></button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Selected SIM */}
          {selections.sim && (
            <div className="border border-pink-200 bg-pink-50 rounded-xl p-3">
              <div className="flex items-center justify-between mb-1">
                <div className="flex items-center gap-1.5 text-xs font-semibold text-pink-700 uppercase tracking-wide"><Smartphone size={11}/> SIM</div>
                <button onClick={() => onRemoveSelection('sim')} className="text-gray-400 hover:text-red-500"><X size={13}/></button>
              </div>
              <p className="text-sm font-medium">{selections.sim.provider}</p>
              <p className="text-xs text-gray-500">{selections.sim.plan_name} · ${selections.sim.price_usd}</p>
              <div className="flex items-center gap-2 mt-0.5 text-xs text-gray-500">
                {selections.sim.data_gb && <span>{selections.sim.data_gb}GB</span>}
                {selections.sim.validity_days && <span>{selections.sim.validity_days} days</span>}
                {selections.sim.network_quality?.speed && <span className="flex items-center gap-0.5"><Wifi size={9}/>{selections.sim.network_quality.speed}</span>}
              </div>
              {selections.sim.url && (
                <a href={selections.sim.url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 text-xs text-pink-600 hover:text-pink-800 font-medium mt-1.5"><ExternalLink size={10} /> Get Plan</a>
              )}
            </div>
          )}

          {/* Selected transport */}
          {selections.getting_around?.length > 0 && (
            <div className="border border-cyan-200 bg-cyan-50 rounded-xl p-3">
              <div className="text-xs font-semibold text-cyan-700 uppercase tracking-wide mb-2 flex items-center gap-1.5"><Bus size={11}/> Getting Around ({selections.getting_around.length})</div>
              <div className="space-y-2">
                {selections.getting_around.map((opt, i) => (
                  <div key={i} className="flex items-start justify-between border-b border-cyan-100 last:border-0 pb-1.5 last:pb-0">
                    <div className="flex-1 min-w-0 mr-2">
                      <p className="text-xs font-medium text-gray-800">{opt.name}</p>
                      <div className="flex items-center gap-2 mt-0.5 text-xs text-gray-500">
                        {opt.type && <span className="capitalize">{opt.type.replace(/_/g, ' ')}</span>}
                        {opt.scope && <span className="capitalize">{opt.scope.replace(/_/g, ' ')}</span>}
                      </div>
                      {opt.price_info && <p className="text-xs text-gray-500 mt-0.5">{opt.price_info}</p>}
                      {opt.booking_url && (
                        <a href={opt.booking_url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 text-xs text-cyan-600 hover:text-cyan-800 font-medium mt-0.5"><ExternalLink size={9} /> More Info</a>
                      )}
                    </div>
                    <button onClick={() => onRemoveSelection('getting_around', opt)} className="text-gray-400 hover:text-red-500 shrink-0 mt-0.5"><X size={12}/></button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Selected tips */}
          {selections.tips?.length > 0 && (
            <div className="border border-amber-200 bg-amber-50 rounded-xl p-3">
              <div className="text-xs font-semibold text-amber-700 uppercase tracking-wide mb-2 flex items-center gap-1.5"><Lightbulb size={11}/> Tips ({selections.tips.length})</div>
              <div className="space-y-2">
                {selections.tips.map((t, i) => (
                  <div key={i} className="flex items-start justify-between border-b border-amber-100 last:border-0 pb-1.5 last:pb-0">
                    <div className="flex-1 min-w-0 mr-2">
                      <div className="flex items-center gap-1.5">
                        <p className="text-xs font-medium text-gray-800">{t.title}</p>
                        {t.severity && <span className={`px-1 py-0.5 rounded text-[10px] font-medium ${t.severity === 'danger' ? 'bg-red-100 text-red-700' : t.severity === 'warning' ? 'bg-yellow-100 text-yellow-700' : 'bg-blue-100 text-blue-700'}`}>{t.severity}</span>}
                      </div>
                      {t.body && <p className="text-xs text-gray-500 mt-0.5 line-clamp-2">{t.body}</p>}
                      {t.source_url && (
                        <a href={t.source_url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 text-xs text-amber-600 hover:text-amber-800 font-medium mt-0.5"><ExternalLink size={9} /> Source</a>
                      )}
                    </div>
                    <button onClick={() => onRemoveSelection('tips', t)} className="text-gray-400 hover:text-red-500 shrink-0 mt-0.5"><X size={12}/></button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Itinerary notes */}
          {Object.entries(selections.itinerary_notes).filter(([,v]) => v).length > 0 && (
            <div className="border border-teal-200 bg-teal-50 rounded-xl p-3">
              <div className="text-xs font-semibold text-teal-700 uppercase tracking-wide mb-2 flex items-center gap-1.5"><PenLine size={11}/> Notes</div>
              <div className="space-y-1.5">
                {Object.entries(selections.itinerary_notes).filter(([,v]) => v).map(([k, v]) => (
                  <div key={k}><p className="text-xs text-teal-600 font-medium capitalize">{k.replace('-', ' – ')}</p><p className="text-xs text-gray-700">{v}</p></div>
                ))}
              </div>
            </div>
          )}

          {/* Selected itinerary slots */}
          {(selections.itinerary_slots?.length > 0) && (
            <div className="border border-teal-200 bg-teal-50 rounded-xl p-3">
              <div className="text-xs font-semibold text-teal-700 uppercase tracking-wide mb-2 flex items-center gap-1.5">
                <Calendar size={11}/> Itinerary ({selections.itinerary_slots.length} slots)
              </div>
              <div className="space-y-1.5">
                {selections.itinerary_slots.map((slot, i) => (
                  <div key={i} className="flex items-start justify-between">
                    <div className="flex-1 min-w-0 mr-2">
                      <p className="text-xs font-medium text-gray-800 truncate">{slot.activity}</p>
                      <p className="text-xs text-teal-500">Day {slot.day_number} · {slot.time_of_day}</p>
                    </div>
                    <button onClick={() => onRemoveSelection('itinerary_slots', slot)} className="text-gray-400 hover:text-red-500 shrink-0"><X size={12}/></button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {selectedCount === 0 && (
            <div
              className={`border-2 border-dashed rounded-xl py-8 px-4 text-center transition-all ${isDragOver ? 'border-teal-400 bg-teal-50 scale-[1.02]' : 'border-gray-200 text-gray-400'}`}
              onDragOver={(e) => { e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; setIsDragOver(true) }}
              onDragLeave={() => setIsDragOver(false)}
              onDrop={(e) => {
                e.preventDefault(); setIsDragOver(false)
                try {
                  const plan = JSON.parse(e.dataTransfer.getData('application/json'))
                  if (plan?.selections) onLoadPlan(plan)
                } catch {}
              }}
            >
              <Bookmark size={32} className={`mx-auto mb-2 ${isDragOver ? 'text-teal-400 opacity-80' : 'opacity-30'}`} />
              {isDragOver
                ? <p className="text-sm text-teal-600 font-medium">Drop to load this plan</p>
                : <>
                    <p className="text-sm">Select flights, hotels &amp; activities<br/>to build your plan</p>
                    <p className="text-xs mt-2 text-gray-300">or drag a saved plan here</p>
                  </>
              }
            </div>
          )}

          {/* Save buttons */}
          <div className="flex gap-2">
            {loadedPlanId && (
              <button onClick={() => { onClearLoadedPlan(); onPlanNameChange('My Trip Plan') }}
                className="px-3 py-2.5 border border-gray-300 text-gray-600 font-medium rounded-xl text-sm hover:bg-gray-50 transition-all shrink-0">
                New
              </button>
            )}
            <button onClick={save} disabled={saving || selectedCount === 0}
              className="flex-1 flex items-center justify-center gap-2 py-2.5 bg-teal-600 text-white font-semibold rounded-xl hover:bg-teal-700 disabled:opacity-50 text-sm transition-all">
              {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
              {saving ? 'Saving…' : loadedPlanId ? 'Update Plan' : 'Save Plan'}
            </button>
          </div>
          {selectedCount > 0 && (
            <button onClick={saveAndClear} disabled={saving}
              className="w-full flex items-center justify-center gap-2 py-2 border border-slate-300 text-slate-600 font-medium rounded-xl text-xs hover:bg-slate-50 hover:border-slate-400 transition-all disabled:opacity-50">
              <Bookmark size={12} /> Save &amp; Send to Saved Plans
            </button>
          )}
          {saveMsg && <p className={`text-sm text-center font-medium ${saveMsg.includes('fail') ? 'text-red-600' : 'text-green-600'}`}>{saveMsg}</p>}

          {/* Saved plans — drop zone for current plan */}
          <div
            onDragOver={(e) => {
              if (e.dataTransfer.types.includes('application/x-current-plan')) {
                e.preventDefault(); e.dataTransfer.dropEffect = 'move'; setIsDragOverSaved(true)
              }
            }}
            onDragLeave={() => setIsDragOverSaved(false)}
            onDrop={(e) => {
              if (e.dataTransfer.types.includes('application/x-current-plan')) {
                e.preventDefault(); setIsDragOverSaved(false); saveAndClear()
              }
            }}
          >
            <h3 className={`text-xs font-semibold uppercase tracking-wide mb-2 px-2 py-1.5 rounded-lg transition-all ${isDragOverSaved ? 'bg-teal-100 text-teal-700 border-2 border-dashed border-teal-400' : 'text-gray-500'}`}>
              {isDragOverSaved ? '↓ Drop here to save plan' : 'Saved Plans'}
            </h3>
            {loadingPlans && <div className="text-xs text-gray-400 text-center py-2">Loading…</div>}
            {savedPlans.length === 0 && !loadingPlans && !isDragOverSaved && (
              <p className="text-xs text-gray-300 text-center py-2">No saved plans yet</p>
            )}
            <div className="space-y-2">
              {savedPlans.map(plan => {
                const planCost = computePlanCost(plan.selections, plan.search_data)
                const planBudget = getBudgetStatus(planCost, plan.search_data?.budget_usd)
                const isLoaded = loadedPlanId === plan.id
                return (
                  <div key={plan.id}
                    draggable
                    onDragStart={(e) => { e.dataTransfer.setData('application/json', JSON.stringify(plan)); e.dataTransfer.effectAllowed = 'copy' }}
                    className={`border rounded-lg px-3 py-2 cursor-grab active:cursor-grabbing transition-all ${isLoaded ? 'border-teal-400 bg-teal-50 ring-1 ring-teal-300' : 'border-gray-200 bg-gray-50 hover:border-gray-300'}`}
                  >
                    <div className="flex items-center justify-between">
                      <div className="min-w-0 flex-1">
                        <p className="text-sm font-medium text-gray-800 truncate">{plan.name}</p>
                        <div className="flex items-center gap-2 mt-0.5">
                          <p className="text-xs text-gray-400">{plan.created_at?.slice(0,10)}</p>
                          {planCost > 0 && <span className="text-xs font-medium text-teal-600">${planCost.toLocaleString(undefined, {maximumFractionDigits:0})}</span>}
                          {planBudget && (
                            <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded-full ${planBudget.status === 'under' ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}`}>
                              {planBudget.label}
                            </span>
                          )}
                        </div>
                      </div>
                      <button onClick={() => deletePlan(plan.id)} disabled={deletingId === plan.id}
                        className="ml-2 text-gray-400 hover:text-red-500 transition-colors shrink-0">
                        {deletingId === plan.id ? <Loader2 size={13} className="animate-spin" /> : <Trash2 size={13} />}
                      </button>
                    </div>
                    <div className="flex gap-1.5 mt-1.5">
                      <button onClick={() => onLoadPlan(plan)}
                        className={`flex-1 flex items-center justify-center gap-1.5 py-1 rounded-md text-xs font-medium transition-colors ${isLoaded ? 'bg-teal-600 text-white' : 'bg-white border border-gray-300 text-gray-700 hover:bg-teal-50 hover:border-teal-400 hover:text-teal-700'}`}>
                        {isLoaded ? <><Check size={11} /> Loaded</> : <><RefreshCw size={11} /> Load</>}
                      </button>
                      <button onClick={() => onViewPlan(plan)}
                        className="flex-1 flex items-center justify-center gap-1.5 py-1 bg-white border border-gray-300 rounded-md text-xs font-medium text-gray-700 hover:bg-teal-50 hover:border-teal-400 hover:text-teal-700 transition-colors">
                        <Eye size={11} /> View
                      </button>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        </div>
      </div>
    </>
  )
}

// ─── Search Panel ─────────────────────────────────────────────────────────────

function SearchPanel({ searchData, isOpen, onToggle, onUpdateSearch }) {
  const today = new Date().toISOString().split('T')[0]
  const [form, setForm] = useState({ ...searchData, budget_usd: searchData.budget_usd ?? '' })
  const INTEREST_LIST = ['food','history','adventure','culture','nature','shopping','nightlife','wellness','art','family']
  const toggle = (id) => setForm(f => ({ ...f, interests: f.interests.includes(id) ? f.interests.filter(i=>i!==id) : [...f.interests, id] }))
  const inputClass = "w-full px-2.5 py-2 border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-teal-400 text-sm bg-white"
  const handleSubmit = (e) => { e.preventDefault(); onUpdateSearch({ ...form, budget_usd: form.budget_usd ? parseFloat(form.budget_usd) : null }) }

  return (
    <div className="bg-white border-b border-gray-200">
      <button onClick={onToggle} className="w-full flex items-center justify-between px-4 py-2.5 hover:bg-gray-50 transition-colors text-sm min-w-0">
        <div className="flex items-center gap-2 text-gray-700 font-medium min-w-0 flex-1">
          <RefreshCw size={14} className="text-teal-500 shrink-0" />
          <span className="shrink-0">Search Criteria</span>
          <span className="text-gray-400 font-normal text-xs truncate hidden sm:inline">
            {searchData.origin} → {searchData.destination} · {searchData.departure_date} · {searchData.num_travelers} traveler{searchData.num_travelers>1?'s':''}
          </span>
        </div>
        {isOpen ? <ChevronUp size={16} className="text-gray-400 shrink-0" /> : <ChevronDown size={16} className="text-gray-400 shrink-0" />}
      </button>

      {isOpen && (
        <form onSubmit={handleSubmit} className="px-4 pb-4 space-y-3 border-t border-gray-100">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 pt-3">
            <AirportSearch label="From" value={form.origin} onChange={v=>setForm(f=>({...f,origin:v}))} placeholder="Origin…" required />
            <AirportSearch label="To" value={form.destination} onChange={v=>setForm(f=>({...f,destination:v}))} placeholder="Destination…" required />
            <div><label className="block text-xs font-medium text-gray-600 mb-1">Departure</label><input type="date" value={form.departure_date} min={today} onChange={e=>setForm(f=>({...f,departure_date:e.target.value}))} className={inputClass} /></div>
            <div><label className="block text-xs font-medium text-gray-600 mb-1">Return</label><input type="date" value={form.return_date} min={form.departure_date} onChange={e=>setForm(f=>({...f,return_date:e.target.value}))} className={inputClass} /></div>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <div><label className="block text-xs font-medium text-gray-600 mb-1">Nationality</label><input type="text" value={form.nationality} onChange={e=>setForm(f=>({...f,nationality:e.target.value}))} className={inputClass} /></div>
            <div><label className="block text-xs font-medium text-gray-600 mb-1">Budget (USD)</label><input type="number" value={form.budget_usd} onChange={e=>setForm(f=>({...f,budget_usd:e.target.value}))} placeholder="Optional" className={inputClass} /></div>
            <div><label className="block text-xs font-medium text-gray-600 mb-1">Travelers</label>
              <div className="flex border border-gray-300 rounded-lg overflow-hidden bg-white">
                <button type="button" onClick={()=>setForm(f=>({...f,num_travelers:Math.max(1,f.num_travelers-1)}))} className="px-2.5 py-2 bg-gray-50 hover:bg-gray-100 text-gray-600 font-bold">−</button>
                <span className="flex-1 text-center py-2 text-sm font-medium">{form.num_travelers}</span>
                <button type="button" onClick={()=>setForm(f=>({...f,num_travelers:Math.min(20,f.num_travelers+1)}))} className="px-2.5 py-2 bg-gray-50 hover:bg-gray-100 text-gray-600 font-bold">+</button>
              </div>
            </div>
            <div className="col-span-1"></div>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <TagInput label="Residence Permits" value={form.residence_permits} onChange={v=>setForm(f=>({...f,residence_permits:v}))} placeholder="Schengen, UK…" />
            <TagInput label="Existing Visas" value={form.existing_visas} onChange={v=>setForm(f=>({...f,existing_visas:v}))} placeholder="US, Japan…" />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Interests</label>
            <div className="flex flex-wrap gap-1.5">
              {INTEREST_LIST.map(id => (
                <button key={id} type="button" onClick={()=>toggle(id)}
                  className={`px-2.5 py-1 rounded-full text-xs font-medium border transition-all ${form.interests.includes(id)?'bg-teal-600 border-teal-600 text-white':'bg-white border-gray-200 text-gray-600 hover:border-teal-300'}`}>
                  {INTEREST_LABELS[id] || id}
                </button>
              ))}
            </div>
          </div>
          <button type="submit" className="flex items-center gap-2 px-5 py-2 bg-teal-600 text-white text-sm font-semibold rounded-lg hover:bg-teal-700 transition-colors">
            <RefreshCw size={14} /> Update Search
          </button>
        </form>
      )}
    </div>
  )
}

// ─── Main ResultsPage ─────────────────────────────────────────────────────────

export default function ResultsPage() {
  const { user, token, logout } = useAuth()
  const { pendingSearchData, clearPendingSearch, showResults, clearSearchResults } = useSearchData()

  const [searchData, setSearchData] = useState(null)
  const [statuses,   setStatuses]   = useState(() => Object.fromEntries(AGENT_ORDER.map(a => [a, 'waiting'])))
  const [results,    setResults]    = useState({})
  const [isDone,     setIsDone]     = useState(false)
  const [error,      setError]      = useState(null)
  const [isSearchPanelOpen, setIsSearchPanelOpen] = useState(false)
  const [isPlanOpen, setIsPlanOpen] = useState(false)
  const [collapsedSections, setCollapsedSections] = useState({})
  const toggleSection = (agent) => setCollapsedSections(prev => ({ ...prev, [agent]: !prev[agent] }))
  const [planName,   setPlanName]   = useState('My Trip Plan')
  const [selections, setSelections] = useState({
    flight: null, hotel: null, activities: [], places_to_see: [], sim: null, tips: [], getting_around: [],
    itinerary_notes: {}, itinerary_edits: {}, itinerary_slots: [],
  })
  const [viewingPlan, setViewingPlan] = useState(null)  // plan object when modal is open
  const [loadedPlanId, setLoadedPlanId] = useState(null)
  const [isFlightFilterOpen, setIsFlightFilterOpen] = useState(false)
  const [isFlightFilterLoading, setIsFlightFilterLoading] = useState(false)
  const [activeFlightFilterCount, setActiveFlightFilterCount] = useState(0)
  const [isHotelFilterOpen, setIsHotelFilterOpen] = useState(false)
  const [isHotelFilterLoading, setIsHotelFilterLoading] = useState(false)
  const [activeHotelFilterCount, setActiveHotelFilterCount] = useState(0)
  const [isActivityFilterOpen, setIsActivityFilterOpen] = useState(false)
  const [isActivityFilterLoading, setIsActivityFilterLoading] = useState(false)
  const [activeActivityFilterCount, setActiveActivityFilterCount] = useState(0)
  const prevCountRef = useRef(0)

  useEffect(() => {
    const count = countSelections(selections)
    if (prevCountRef.current === 0 && count > 0 && !loadedPlanId) {
      setPlanName(generatePlanName(searchData?.destination, searchData?.interests, searchData?.departure_date))
    }
    prevCountRef.current = count
  }, [selections, searchData, loadedPlanId])

  const handleLoadPlan = (plan) => {
    setSelections({ ...EMPTY_SELECTIONS, ...(plan.selections || {}) })
    setPlanName(plan.name)
    setLoadedPlanId(plan.id)
  }


  const hasStarted = useRef(false)
  const cleanupWorker = useRef(null)
  // Selections to pre-populate after a search re-run (used by load-plan)
  const pendingSelections = useRef(null)

  const runSearch = (sd, preloadSelections = null) => {
    setStatuses(Object.fromEntries(AGENT_ORDER.map(a => [a, 'waiting'])))
    setResults({})
    setIsDone(false)
    setError(null)
    setLoadedPlanId(null)
    setActiveFlightFilterCount(0)
    setActiveHotelFilterCount(0)
    setActiveActivityFilterCount(0)
    hasStarted.current = false
    pendingSelections.current = preloadSelections

    if (preloadSelections) {
      setSelections(preloadSelections)
    } else {
      setSelections({ flight: null, hotel: null, activities: [], places_to_see: [], sim: null, tips: [], getting_around: [], itinerary_notes: {}, itinerary_edits: {}, itinerary_slots: [] })
    }

    // Small delay so state resets before the effect re-fires
    setTimeout(() => {
      setSearchData({ ...sd })
      hasStarted.current = false
    }, 50)
  }

  useEffect(() => {
    if (pendingSearchData) {
      showResults()
      runSearch(pendingSearchData)
      clearPendingSearch()
    }
  }, [pendingSearchData])

  // Kick off SSE whenever searchData changes (with hasStarted guard)
  useEffect(() => {
    if (!searchData || hasStarted.current) return
    hasStarted.current = true

    setStatuses(s => ({ ...s, flights:'loading', hotels:'loading', activities:'loading', places_to_see:'loading', visa:'loading', sim:'loading', tips:'loading', getting_around:'loading', forex:'loading', itinerary:'waiting' }))

    if (cleanupWorker.current) cleanupWorker.current()

    cleanupWorker.current = streamSearch(
      searchData,
      (type, data, source) => {
        if (!AGENT_ORDER.includes(type)) return
        startTransition(() => {
          setResults(r => {
            if (source === 'ai' && data?.error && r[type] && !r[type]?.error) return r
            return { ...r, [type]: data }
          })
        })
        setStatuses(prev => {
          const isStatic = source === 'static'
          // Static results show immediately but with 'enhancing' status;
          // AI results always mark as 'done'
          const next = { ...prev, [type]: isStatic ? 'enhancing' : 'done' }
          // Itinerary starts as soon as its two inputs (activities+hotels) are ready
          if ((next.activities === 'done' || next.activities === 'enhancing') &&
              (next.hotels === 'done' || next.hotels === 'enhancing') &&
              next.itinerary === 'waiting') {
            next.itinerary = 'loading'
          }
          return next
        })
      },
      () => {
        setIsDone(true)
        // If itinerary never arrived, generate client-side fallback so section always renders
        setResults(prev => {
          if (prev.itinerary?.days?.length) return prev
          const fallback = buildClientItinerary(prev.activities, prev.hotels, searchData)
          return fallback ? { ...prev, itinerary: fallback } : prev
        })
        setStatuses(prev => {
          if (prev.itinerary === 'waiting' || prev.itinerary === 'loading') {
            return { ...prev, itinerary: 'done' }
          }
          return prev
        })
      },
      (err) => setError(err.message || 'Search error'),
    )
  }, [searchData])

  if (!searchData) return null

  const completedCount = Object.values(statuses).filter(s => s === 'done' || s === 'enhancing').length
  const selectedCount  = (selections.flight ? 1 : 0) + (selections.hotel ? 1 : 0) + selections.activities.length + (selections.places_to_see?.length || 0) + (selections.sim ? 1 : 0) + (selections.getting_around?.length || 0) + (selections.itinerary_slots?.length || 0)

  const handleSelect = (type, value) => {
    if (type === 'activities') {
      setSelections(s => {
        const already = s.activities.some(a => a.name === value.name)
        return { ...s, activities: already ? s.activities.filter(a => a.name !== value.name) : [...s.activities, value] }
      })
    } else if (type === 'tips') {
      setSelections(s => {
        const already = s.tips.some(t => t.title === value.title)
        return { ...s, tips: already ? s.tips.filter(t => t.title !== value.title) : [...s.tips, value] }
      })
    } else if (type === 'getting_around') {
      setSelections(s => {
        const already = s.getting_around.some(a => a.name === value.name)
        return { ...s, getting_around: already ? s.getting_around.filter(a => a.name !== value.name) : [...s.getting_around, value] }
      })
    } else if (type === 'places_to_see') {
      setSelections(s => {
        const already = (s.places_to_see || []).some(p => p.name === value.name)
        return { ...s, places_to_see: already ? (s.places_to_see || []).filter(p => p.name !== value.name) : [...(s.places_to_see || []), value] }
      })
    } else {
      setSelections(s => ({ ...s, [type]: value }))
    }
  }

  const handleNoteChange = (key, text) => setSelections(s => ({ ...s, itinerary_notes: { ...s.itinerary_notes, [key]: text } }))

  const handleSlotEdit = (key, field, value) => setSelections(s => ({
    ...s,
    itinerary_edits: {
      ...s.itinerary_edits,
      [key]: { ...(s.itinerary_edits[key] || {}), [field]: value },
    },
  }))

  const handleRemoveSelection = (type, value) => {
    if (type === 'activities') {
      setSelections(s => ({ ...s, activities: s.activities.filter(a => a.name !== value.name) }))
    } else if (type === 'getting_around') {
      setSelections(s => ({ ...s, getting_around: s.getting_around.filter(a => a.name !== value.name) }))
    } else if (type === 'tips') {
      setSelections(s => ({ ...s, tips: s.tips.filter(t => t.title !== value.title) }))
    } else if (type === 'places_to_see') {
      setSelections(s => ({ ...s, places_to_see: (s.places_to_see || []).filter(p => p.name !== value.name) }))
    } else if (type === 'itinerary_slots') {
      setSelections(s => ({ ...s, itinerary_slots: (s.itinerary_slots || []).filter(sl => sl.key !== value.key) }))
    } else {
      setSelections(s => ({ ...s, [type]: null }))
    }
  }

  const handleSlotPlan = (key, slotObj) => {
    setSelections(s => {
      const slots = s.itinerary_slots || []
      const exists = slots.some(sl => sl.key === key)
      return {
        ...s,
        itinerary_slots: exists ? slots.filter(sl => sl.key !== key) : [...slots, slotObj]
      }
    })
  }

  const handleApplyFlightFilters = async (filters) => {
    const filterCount = Object.keys(filters).length
    setActiveFlightFilterCount(filterCount)
    setIsFlightFilterLoading(true)
    setStatuses(s => ({ ...s, flights: 'loading' }))
    setIsFlightFilterOpen(false)
    setCollapsedSections(prev => ({ ...prev, flights: false }))
    try {
      const data = await searchFlightsFiltered(searchData, filters)
      setResults(r => ({ ...r, flights: data }))
      setStatuses(s => ({ ...s, flights: 'done' }))
    } catch (err) {
      setStatuses(s => ({ ...s, flights: 'done' }))
    } finally {
      setIsFlightFilterLoading(false)
    }
  }

  const handleApplyHotelFilters = async (filters) => {
    const filterCount = Object.keys(filters).length
    setActiveHotelFilterCount(filterCount)
    setIsHotelFilterLoading(true)
    setStatuses(s => ({ ...s, hotels: 'loading' }))
    setIsHotelFilterOpen(false)
    setCollapsedSections(prev => ({ ...prev, hotels: false }))
    try {
      const data = await searchHotelsFiltered(searchData, filters)
      setResults(r => ({ ...r, hotels: data }))
      setStatuses(s => ({ ...s, hotels: 'done' }))
    } catch (err) {
      setStatuses(s => ({ ...s, hotels: 'done' }))
    } finally {
      setIsHotelFilterLoading(false)
    }
  }

  const handleApplyActivityFilters = async (filters) => {
    const filterCount = Object.keys(filters).length
    setActiveActivityFilterCount(filterCount)
    setIsActivityFilterLoading(true)
    setStatuses(s => ({ ...s, activities: 'loading' }))
    setIsActivityFilterOpen(false)
    setCollapsedSections(prev => ({ ...prev, activities: false }))
    try {
      const data = await searchActivitiesFiltered(searchData, filters)
      setResults(r => ({ ...r, activities: data }))
      setStatuses(s => ({ ...s, activities: 'done' }))
    } catch (err) {
      setStatuses(s => ({ ...s, activities: 'done' }))
    } finally {
      setIsActivityFilterLoading(false)
    }
  }

  const scrollToSection = (agent) => {
    setCollapsedSections(prev => ({ ...prev, [agent]: false }))
    requestAnimationFrame(() => {
      const el = document.getElementById(`section-${agent}`)
      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
    })
  }

  const sectionProps = { selections, onSelect: handleSelect }

  const renderSectionCard = (agent, extraStyle = {}) => {
    const status = statuses[agent]
    if (status === 'waiting') return null
    const data = results[agent]
    const renderers = {
      flights:        () => <FlightsSection    data={data} {...sectionProps} />,
      hotels:         () => <HotelsSection     data={data} {...sectionProps} />,
      activities:     () => <ActivitiesSection   data={data} {...sectionProps} />,
      places_to_see:  () => <PlacesToSeeSection  data={data} {...sectionProps} />,
      visa:           () => <VisaSection         data={data} />,
      sim:            () => <SimSection        data={data} {...sectionProps} />,
      tips:           () => <TipsSection       data={data} {...sectionProps} />,
      getting_around: () => <GettingAroundSection data={data} {...sectionProps} />,
      forex:          () => <ForexSection data={data} />,
      itinerary:      () => <ItinerarySection  data={data} selections={selections} onNoteChange={handleNoteChange} onSlotEdit={handleSlotEdit} onSlotPlan={handleSlotPlan} />,
    }
    const isOpen = !collapsedSections[agent]
    const filterAction = (() => {
      const ready = status === 'done' || status === 'enhancing'
      if (agent === 'flights' && ready) return (
        <button onClick={e => { e.stopPropagation(); setIsFlightFilterOpen(true) }}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold bg-white/20 hover:bg-white/30 backdrop-blur-sm transition-all border border-white/20">
          <SlidersHorizontal size={12} /><span>Filters</span>
          {activeFlightFilterCount > 0 && <span className="flex items-center justify-center w-4 h-4 rounded-full bg-white text-sky-600 text-[10px] font-bold">{activeFlightFilterCount}</span>}
        </button>
      )
      if (agent === 'hotels' && ready) return (
        <button onClick={e => { e.stopPropagation(); setIsHotelFilterOpen(true) }}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold bg-white/20 hover:bg-white/30 backdrop-blur-sm transition-all border border-white/20">
          <SlidersHorizontal size={12} /><span>Filters</span>
          {activeHotelFilterCount > 0 && <span className="flex items-center justify-center w-4 h-4 rounded-full bg-white text-violet-600 text-[10px] font-bold">{activeHotelFilterCount}</span>}
        </button>
      )
      if (agent === 'activities' && ready) return (
        <button onClick={e => { e.stopPropagation(); setIsActivityFilterOpen(true) }}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold bg-white/20 hover:bg-white/30 backdrop-blur-sm transition-all border border-white/20">
          <SlidersHorizontal size={12} /><span>Filters</span>
          {activeActivityFilterCount > 0 && <span className="flex items-center justify-center w-4 h-4 rounded-full bg-white text-emerald-600 text-[10px] font-bold">{activeActivityFilterCount}</span>}
        </button>
      )
      return null
    })()
    return (
      <div key={agent} id={`section-${agent}`} className="bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden transition-all duration-500" style={{ animation: 'fadeSlideIn 0.5s ease-out forwards', scrollMarginTop: '12rem', ...extraStyle }}>
        <SectionHeader agent={agent} status={status} isOpen={isOpen} onToggle={() => toggleSection(agent)} actions={filterAction} />
        {isOpen && (
          status === 'loading' ? <Skeleton agent={agent} /> : data ? renderers[agent]() : <div className="p-4 text-sm text-gray-500">No results</div>
        )}
      </div>
    )
  }

  const completionBanner = isDone && (
    <div className="text-center py-8">
      <div className="inline-flex flex-col items-center gap-3 px-8 py-5 bg-gradient-to-r from-green-50 to-emerald-50 border border-green-200 rounded-2xl">
        <div className="w-12 h-12 rounded-full bg-green-100 flex items-center justify-center">
          <CheckCircle2 size={24} className="text-green-600" />
        </div>
        <div>
          <p className="text-green-800 font-bold text-lg">Your travel plan is ready!</p>
          <p className="text-green-600 text-sm mt-1">Browse the sections above and add items to your plan</p>
        </div>
      </div>
    </div>
  )

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Sticky header: top bar + badges */}
      <div className="sticky top-14 z-30">
        {/* Top bar */}
        <div className="bg-gradient-to-r from-slate-500 to-slate-600 text-white shadow-md">
          <div className="max-w-6xl mx-auto px-4 py-3">
            <div className="flex items-center justify-between gap-2 sm:gap-4">
              <button onClick={() => clearSearchResults()} className="flex items-center gap-1 sm:gap-1.5 text-slate-200 hover:text-white text-xs sm:text-sm shrink-0">
                <ArrowLeft size={14}/><span className="hidden xs:inline">New Search</span><span className="xs:hidden">Back</span>
              </button>
              <div className="text-center min-w-0 flex-1">
                <p className="font-semibold text-xs sm:text-sm truncate">{searchData.origin} → {searchData.destination}</p>
                <p className="text-slate-300 text-[10px] sm:text-xs hidden sm:block">{searchData.departure_date}{searchData.return_date ? ` – ${searchData.return_date}` : ''} · {searchData.num_travelers} traveler{searchData.num_travelers>1?'s':''}</p>
              </div>
              <div className="flex items-center gap-2 sm:gap-3 shrink-0">
                {isDone ? <span className="flex items-center gap-1 text-green-300 text-xs sm:text-sm"><CheckCircle2 size={13}/><span className="hidden sm:inline"> Done</span></span> : <span className="text-blue-200 text-xs sm:text-sm">{completedCount}/{AGENT_ORDER.length}</span>}
              </div>
            </div>
          </div>
        </div>

        {/* Search panel */}
        <SearchPanel searchData={searchData} isOpen={isSearchPanelOpen} onToggle={() => setIsSearchPanelOpen(v=>!v)} onUpdateSearch={(sd) => { setIsSearchPanelOpen(false); runSearch(sd) }} />

        {/* Progress strip */}
        <div className="bg-white/95 backdrop-blur-sm border-b border-gray-200 shadow-sm">
        <div className="max-w-6xl mx-auto px-4 py-2.5">
          <div className="flex flex-wrap gap-1.5 justify-center">
            {AGENT_ORDER.map(agent => <AgentBadge key={agent} agent={agent} status={statuses[agent]} onClick={scrollToSection} />)}
          </div>
          {!isDone && (
            <div className="mt-2 bg-gray-200 rounded-full h-1 overflow-hidden">
              <div className="bg-gradient-to-r from-teal-400 to-sky-400 h-full rounded-full transition-all duration-500" style={{ width: `${(completedCount/AGENT_ORDER.length)*100}%` }} />
            </div>
          )}
        </div>
      </div>
      </div>

      {/* Animated destination summary */}
      {!isDone && completedCount < AGENT_ORDER.length && (
        <div className="bg-gradient-to-r from-teal-50 via-sky-50 to-violet-50 border-b border-gray-100">
          <div className="max-w-6xl mx-auto px-4 py-4 flex items-center gap-4">
            <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-teal-500 to-sky-500 flex items-center justify-center shadow-md">
              <Globe size={24} className="text-white" />
            </div>
            <div>
              <h2 className="text-lg font-bold text-gray-800">Planning your trip to {searchData.destination}</h2>
              <p className="text-sm text-gray-500">
                {completedCount === 0 ? "Getting everything ready for you..."
                 : completedCount < 4 ? `Found ${completedCount} results so far — more coming!`
                 : `Almost there! ${completedCount} of ${AGENT_ORDER.length} sections ready.`}
              </p>
            </div>
          </div>
        </div>
      )}

      {error && (
        <div className="max-w-6xl mx-auto px-4 py-3">
          <div className="bg-red-50 border border-red-200 rounded-xl p-3 text-red-700 text-sm flex items-center gap-2">
            <AlertCircle size={15}/>{error}
          </div>
        </div>
      )}

      {/* Results */}
      <div className="max-w-6xl mx-auto px-4 py-5 space-y-5 pb-24">
        {AGENT_ORDER.map(agent => renderSectionCard(agent, { animationDelay: `${AGENT_ORDER.indexOf(agent) * 80}ms` }))}
        {completionBanner}
      </div>

      {/* Floating plan button */}
      <button onClick={() => setIsPlanOpen(true)}
        className="fixed bottom-6 right-6 z-40 flex items-center gap-2 px-4 py-3 bg-teal-600 text-white font-semibold rounded-full shadow-xl hover:shadow-2xl hover:bg-teal-700 transition-all">
        <Bookmark size={16} />
        <span className="text-sm">My Plan</span>
        {selectedCount > 0 && (
          <span className="bg-white text-teal-700 text-xs font-bold w-5 h-5 rounded-full flex items-center justify-center">{selectedCount}</span>
        )}
        {computePlanCost(selections, searchData) > 0 && (
          <span className="text-teal-100 text-xs font-medium">${computePlanCost(selections, searchData).toLocaleString(undefined, {maximumFractionDigits:0})}</span>
        )}
      </button>

      {/* My Plan Drawer */}
      <MyPlanDrawer
        isOpen={isPlanOpen}
        onClose={() => setIsPlanOpen(false)}
        selections={selections}
        planName={planName}
        onPlanNameChange={setPlanName}
        onRemoveSelection={handleRemoveSelection}
        onViewPlan={(plan) => setViewingPlan(plan)}
        token={token}
        searchData={searchData}
        results={results}
        loadedPlanId={loadedPlanId}
        onLoadPlan={handleLoadPlan}
        onClearLoadedPlan={() => setLoadedPlanId(null)}
        onClearSelections={() => setSelections({ ...EMPTY_SELECTIONS })}
      />

      {viewingPlan && (
        <PlanViewModal
          plan={viewingPlan}
          token={token}
          onClose={() => setViewingPlan(null)}
          onSaved={(updated) => {
            // Update the plan in the drawer's list if it's open
            setViewingPlan(updated)
          }}
          onDeleted={() => setViewingPlan(null)}
        />
      )}

      {/* Flight Filter Modal */}
      <FlightFilterModal
        isOpen={isFlightFilterOpen}
        onClose={() => setIsFlightFilterOpen(false)}
        onApply={handleApplyFlightFilters}
        currentResults={results.flights}
        isLoading={isFlightFilterLoading}
      />

      {/* Hotel Filter Modal */}
      <HotelFilterModal
        isOpen={isHotelFilterOpen}
        onClose={() => setIsHotelFilterOpen(false)}
        onApply={handleApplyHotelFilters}
        currentResults={results.hotels}
        isLoading={isHotelFilterLoading}
      />

      {/* Activity Filter Modal */}
      <ActivityFilterModal
        isOpen={isActivityFilterOpen}
        onClose={() => setIsActivityFilterOpen(false)}
        onApply={handleApplyActivityFilters}
        currentResults={results.activities}
        isLoading={isActivityFilterLoading}
        searchData={searchData}
      />
    </div>
  )
}
