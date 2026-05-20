import React, { useState, useRef, useEffect, useCallback } from 'react'
import { useAuth } from '../context/AuthContext'
import {
  Send, Square, Plane, User, Trash2, Hotel, MapPin, Shield,
  Smartphone, Lightbulb, Calendar, CheckCircle2, Loader2, Clock,
  Star, AlertTriangle, Info, AlertCircle, ExternalLink,
  DollarSign, Zap, X, Check, Copy, Plus, Bookmark, Save, Eye,
  ChevronDown, ChevronUp, PenLine, Bus, RefreshCw, Wifi
} from 'lucide-react'
import PlanViewModal from '../components/PlanViewModal'
import { generatePlanName, computePlanCost, getBudgetStatus, countSelections, EMPTY_SELECTIONS } from '../utils/planHelpers'
import { track } from '../utils/analytics'

// ─── Agent config (reused from ResultsPage) ─────────────────────────────────

const AGENT_CONFIG = {
  flights:        { label: 'Flights',        icon: Plane,      color: 'sky'     },
  hotels:         { label: 'Hotels',         icon: Hotel,      color: 'violet'  },
  activities:     { label: 'Activities',     icon: MapPin,     color: 'emerald' },
  visa:           { label: 'Visa',           icon: Shield,     color: 'orange'  },
  sim:            { label: 'SIM Cards',      icon: Smartphone, color: 'rose'    },
  tips:           { label: 'Travel Tips',    icon: Lightbulb,  color: 'amber'   },
  getting_around: { label: 'Getting Around', icon: Bus,        color: 'cyan'    },
  forex:          { label: 'Currency & Forex', icon: DollarSign, color: 'emerald' },
  itinerary:      { label: 'Itinerary',      icon: Calendar,   color: 'teal'    },
}

const CHAT_COLORS = {
  sky:     { bg: 'bg-sky-50',     border: 'border-sky-100',     text: 'text-sky-800' },
  violet:  { bg: 'bg-violet-50',  border: 'border-violet-100',  text: 'text-violet-800' },
  emerald: { bg: 'bg-emerald-50', border: 'border-emerald-100', text: 'text-emerald-800' },
  orange:  { bg: 'bg-orange-50',  border: 'border-orange-100',  text: 'text-orange-800' },
  rose:    { bg: 'bg-rose-50',    border: 'border-rose-100',    text: 'text-rose-800' },
  amber:   { bg: 'bg-amber-50',   border: 'border-amber-100',   text: 'text-amber-800' },
  cyan:    { bg: 'bg-cyan-50',    border: 'border-cyan-100',    text: 'text-cyan-800' },
  teal:    { bg: 'bg-teal-50',    border: 'border-teal-100',    text: 'text-teal-800' },
}

// ─── Chat streaming function ─────────────────────────────────────────────────

function streamChat(messages, onEvent, onDone, onError, token, selections, searchResults, sessionContext) {
  const worker = new Worker(
    new URL('../workers/chatWorker.js', import.meta.url),
    { type: 'module' }
  )

  worker.onmessage = ({ data }) => {
    if (data.type === '__error') {
      onError(new Error(data.message))
      worker.terminate()
    } else if (data.type === '__stream_end') {
      onDone()
      worker.terminate()
    } else {
      onEvent(data)
    }
  }

  worker.onerror = (e) => {
    onError(new Error(e.message || 'Worker error'))
    worker.terminate()
  }

  worker.postMessage({
    url: '/api/chat',
    headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: JSON.stringify({ messages, selections: selections || {}, search_results: searchResults || {}, session_context: sessionContext || {} }),
  })

  return () => worker.terminate()
}

// ─── Section renderers (compact for chat) ────────────────────────────────────

function ChatFlightsSection({ data, selections, onSelect, isExpanded, onToggleExpand }) {
  if (!data?.results?.length) return <p className="text-xs text-gray-500">No flights found</p>
  const LIMIT = 5
  const selected = selections.flight
  const items = data.results
  const visible = isExpanded ? items : items.slice(0, LIMIT)
  const hidden = items.length - LIMIT
  return (
    <div className="space-y-2">
      {visible.map((f, i) => {
        const isSelected = selected?.price_usd === f.price_usd && selected?.outbound?.airline === f.outbound?.airline
        return (
          <div key={i} onClick={() => onSelect('flight', isSelected ? null : f)}
            className={`border rounded-lg p-2.5 cursor-pointer text-xs transition-all ${isSelected ? 'border-sky-400 bg-sky-50 ring-1 ring-sky-300' : 'border-gray-200 hover:shadow-sm'}`}>
            <div className="flex justify-between items-center">
              <span className="font-medium text-gray-900">{f.outbound?.airline || f.airline || '—'}{f.outbound?.flight_number ? ` ${f.outbound.flight_number}` : ''}</span>
              <span className="font-bold text-sky-700">{f.price_usd ? `$${f.price_usd.toLocaleString()}` : '—'}</span>
            </div>
            {f.outbound && <p className="text-gray-500">{f.outbound.origin} → {f.outbound.destination}{f.return ? ` (round-trip)` : ''}</p>}
            <div className="flex items-center gap-2 mt-1">
              {f.booking_url && <a href={f.booking_url} target="_blank" rel="noopener noreferrer" onClick={e => e.stopPropagation()} className="text-sky-600 hover:text-sky-800 font-medium flex items-center gap-0.5"><ExternalLink size={9} /> Book</a>}
              {isSelected && <span className="text-sky-700 font-semibold flex items-center gap-0.5"><Check size={9} /> In Plan</span>}
            </div>
          </div>
        )
      })}
      {!isExpanded && hidden > 0 && (
        <button onClick={onToggleExpand} className="w-full text-xs text-sky-600 hover:text-sky-800 font-medium py-1.5 border border-dashed border-sky-200 rounded-lg hover:bg-sky-50 transition-all">
          Show {hidden} more →
        </button>
      )}
      {isExpanded && items.length > LIMIT && (
        <button onClick={onToggleExpand} className="w-full text-xs text-gray-400 hover:text-gray-600 font-medium py-1">Show less</button>
      )}
    </div>
  )
}

function ChatHotelsSection({ data, selections, onSelect, isExpanded, onToggleExpand }) {
  if (!data?.results?.length) return <p className="text-xs text-gray-500">No hotels found</p>
  const LIMIT = 5
  const selected = selections.hotel
  const items = data.results
  const visible = isExpanded ? items : items.slice(0, LIMIT)
  const hidden = items.length - LIMIT
  return (
    <div className="space-y-2">
      {visible.map((h, i) => {
        const isSelected = selected?.name === h.name
        return (
          <div key={i} className={`border rounded-lg p-2.5 text-xs transition-all ${isSelected ? 'border-violet-400 bg-violet-50 ring-1 ring-violet-300' : 'border-gray-200 hover:shadow-sm'}`}>
            <div className="flex justify-between items-start">
              <div className="flex-1 min-w-0 mr-2">
                <p className="font-medium text-gray-900 truncate">{h.name}</p>
                <p className="text-gray-500">{h.location}</p>
                <div className="flex items-center gap-1 mt-0.5">
                  {h.star_rating > 0 && <div className="flex">{[...Array(Math.round(h.star_rating))].map((_, j) => <Star key={j} size={8} className="text-yellow-400 fill-yellow-400" />)}</div>}
                  {h.booking_url && <a href={h.booking_url} target="_blank" rel="noopener noreferrer" className="text-violet-600 hover:text-violet-800 font-medium flex items-center gap-0.5 ml-1"><ExternalLink size={9} /> Book</a>}
                </div>
              </div>
              <div className="text-right shrink-0">
                <p className="font-bold text-violet-700">${h.price_per_night_usd?.toLocaleString()}<span className="font-normal text-gray-400">/n</span></p>
                <button onClick={() => onSelect('hotel', isSelected ? null : h)}
                  className={`mt-1 px-2 py-0.5 rounded-full text-[10px] font-semibold ${isSelected ? 'bg-violet-600 text-white' : 'bg-gray-100 text-gray-500 hover:bg-violet-100'}`}>
                  {isSelected ? <><Check size={8}/> Added</> : <><Plus size={8}/> Add</>}
                </button>
              </div>
            </div>
          </div>
        )
      })}
      {!isExpanded && hidden > 0 && (
        <button onClick={onToggleExpand} className="w-full text-xs text-violet-600 hover:text-violet-800 font-medium py-1.5 border border-dashed border-violet-200 rounded-lg hover:bg-violet-50 transition-all">
          Show {hidden} more →
        </button>
      )}
      {isExpanded && items.length > LIMIT && (
        <button onClick={onToggleExpand} className="w-full text-xs text-gray-400 hover:text-gray-600 font-medium py-1">Show less</button>
      )}
    </div>
  )
}

function ChatActivitiesSection({ data, selections, onSelect, isExpanded, onToggleExpand }) {
  if (!data?.results?.length) return <p className="text-xs text-gray-500">No activities found</p>
  const LIMIT = 8
  const items = data.results
  const visible = isExpanded ? items : items.slice(0, LIMIT)
  const hidden = items.length - LIMIT
  return (
    <div className="space-y-1.5">
      {visible.map((a, i) => {
        const isSelected = selections.activities.some(x => x.name === a.name)
        return (
          <div key={i} className={`flex items-center justify-between border rounded-lg p-2 text-xs ${isSelected ? 'border-emerald-400 bg-emerald-50' : 'border-gray-200'}`}>
            <div className="flex-1 min-w-0 mr-2">
              <p className="font-medium text-gray-900 truncate">{a.name}</p>
              <div className="flex items-center gap-2 text-gray-500">
                {a.price_usd != null && <span>${a.price_usd}</span>}
                {a.duration_hours && <span>{a.duration_hours}h</span>}
                {a.booking_url && <a href={a.booking_url} target="_blank" rel="noopener noreferrer" onClick={e => e.stopPropagation()} className="text-emerald-600 hover:text-emerald-800 font-medium flex items-center gap-0.5"><ExternalLink size={8} /> Book</a>}
              </div>
            </div>
            <button onClick={() => onSelect('activities', a)}
              className={`px-2 py-0.5 rounded-full text-[10px] font-semibold shrink-0 ${isSelected ? 'bg-emerald-600 text-white' : 'bg-gray-100 text-gray-500 hover:bg-emerald-100'}`}>
              {isSelected ? <><Check size={8}/> Added</> : <><Plus size={8}/> Add</>}
            </button>
          </div>
        )
      })}
      {!isExpanded && hidden > 0 && (
        <button onClick={onToggleExpand} className="w-full text-xs text-emerald-600 hover:text-emerald-800 font-medium py-1.5 border border-dashed border-emerald-200 rounded-lg hover:bg-emerald-50 transition-all">
          Show {hidden} more →
        </button>
      )}
      {isExpanded && items.length > LIMIT && (
        <button onClick={onToggleExpand} className="w-full text-xs text-gray-400 hover:text-gray-600 font-medium py-1">Show less</button>
      )}
    </div>
  )
}

function ChatSimSection({ data, selections, onSelect, isExpanded, onToggleExpand }) {
  if (!data?.plans?.length) return <p className="text-xs text-gray-500">No SIM plans found</p>
  const LIMIT = 5
  const selected = selections.sim
  const items = data.plans
  const visible = isExpanded ? items : items.slice(0, LIMIT)
  const hidden = items.length - LIMIT
  return (
    <div className="space-y-1.5">
      {visible.map((p, i) => {
        const isSelected = selected?.provider === p.provider && selected?.plan_name === p.plan_name
        return (
          <div key={i} className={`flex items-center justify-between border rounded-lg p-2 text-xs ${isSelected ? 'border-rose-400 bg-rose-50' : 'border-gray-200'}`}>
            <div className="flex-1 min-w-0 mr-2">
              <p className="font-medium text-gray-900">{p.provider} — {p.plan_name}</p>
              <div className="flex items-center gap-2 text-gray-500">
                <span className="font-bold text-rose-700">${p.price_usd}</span>
                {p.data_gb && <span>{p.data_gb}GB</span>}
                {p.validity_days && <span>{p.validity_days}d</span>}
                {p.network_quality?.speed && <span className="flex items-center gap-0.5"><Wifi size={8}/>{p.network_quality.speed}</span>}
                {p.network_quality?.coverage_rating && <span className={`px-1 py-0.5 rounded-full text-[9px] font-medium ${p.network_quality.coverage_rating === 'excellent' ? 'bg-green-100 text-green-700' : p.network_quality.coverage_rating === 'good' ? 'bg-blue-100 text-blue-700' : p.network_quality.coverage_rating === 'moderate' ? 'bg-yellow-100 text-yellow-700' : 'bg-red-100 text-red-700'}`}>{p.network_quality.coverage_rating}</span>}
                {p.url && <a href={p.url} target="_blank" rel="noopener noreferrer" className="text-rose-600 hover:text-rose-800 font-medium flex items-center gap-0.5"><ExternalLink size={8} /> Get</a>}
              </div>
            </div>
            <button onClick={() => onSelect('sim', isSelected ? null : p)}
              className={`px-2 py-0.5 rounded-full text-[10px] font-semibold shrink-0 ${isSelected ? 'bg-rose-600 text-white' : 'bg-gray-100 text-gray-500 hover:bg-rose-100'}`}>
              {isSelected ? <><Check size={8}/> Added</> : <><Plus size={8}/> Add</>}
            </button>
          </div>
        )
      })}
      {!isExpanded && hidden > 0 && (
        <button onClick={onToggleExpand} className="w-full text-xs text-rose-600 hover:text-rose-800 font-medium py-1.5 border border-dashed border-rose-200 rounded-lg hover:bg-rose-50 transition-all">
          Show {hidden} more →
        </button>
      )}
      {isExpanded && items.length > LIMIT && (
        <button onClick={onToggleExpand} className="w-full text-xs text-gray-400 hover:text-gray-600 font-medium py-1">Show less</button>
      )}
    </div>
  )
}

function ChatVisaSection({ data }) {
  const req = data?.requirement
  if (!req) return <p className="text-xs text-gray-500">No visa info available</p>
  const typeColors = { 'visa-free':'bg-green-100 text-green-800','visa-on-arrival':'bg-blue-100 text-blue-800','e-visa':'bg-yellow-100 text-yellow-800','visa-required':'bg-red-100 text-red-800' }
  return (
    <div className="text-xs space-y-1.5">
      <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-bold ${typeColors[req.visa_type] || 'bg-gray-100 text-gray-700'}`}>{req.visa_type?.replace(/-/g, ' ').toUpperCase()}</span>
      <div className="flex gap-3 text-gray-600">
        {req.max_stay_days && <span>Max stay: {req.max_stay_days}d</span>}
        {req.fee_usd != null && <span>Fee: {req.fee_usd === 0 ? 'Free' : `$${req.fee_usd}`}</span>}
        {req.processing_time && <span>{req.processing_time}</span>}
      </div>
      {req.requirements?.length > 0 && <ul className="list-disc list-inside text-gray-600 space-y-0.5">{req.requirements.slice(0, 5).map((r, i) => <li key={i}>{r}</li>)}</ul>}
      {req.official_url && <a href={req.official_url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 text-orange-600 hover:text-orange-800 font-medium"><ExternalLink size={9} /> Official Source</a>}
    </div>
  )
}

function ChatTipsSection({ data, selections, onSelect, isExpanded, onToggleExpand }) {
  if (!data?.tips?.length) return <p className="text-xs text-gray-500">No tips available</p>
  const LIMIT = 8
  const sc = { danger: 'bg-red-50 border-red-200 text-red-800', warning: 'bg-yellow-50 border-yellow-200 text-yellow-800', info: 'bg-blue-50 border-blue-200 text-blue-800' }
  const selectedTips = selections.tips || []
  const items = data.tips
  const visible = isExpanded ? items : items.slice(0, LIMIT)
  const hidden = items.length - LIMIT
  return (
    <div className="space-y-1.5">
      {visible.map((tip, i) => {
        const isSelected = selectedTips.some(t => t.title === tip.title)
        return (
          <div key={i} className={`flex items-center justify-between gap-2 p-2 rounded-lg border text-xs ${sc[tip.severity] || sc.info}`}>
            <div className="flex-1 min-w-0">
              <p className="font-semibold text-gray-900">{tip.title}</p>
              <p className="mt-0.5">{tip.body?.slice(0, 120)}{tip.body?.length > 120 ? '...' : ''}</p>
              {tip.source_url && <a href={tip.source_url} target="_blank" rel="noopener noreferrer" className="text-teal-600 hover:text-teal-800 font-medium flex items-center gap-0.5 mt-1"><ExternalLink size={8} /> Source</a>}
            </div>
            <button onClick={() => onSelect('tips', tip)}
              className={`px-2 py-0.5 rounded-full text-[10px] font-semibold shrink-0 ${isSelected ? 'bg-amber-500 text-white' : 'bg-gray-100 text-gray-500 hover:bg-amber-100'}`}>
              {isSelected ? <><Check size={8}/> Added</> : <><Plus size={8}/> Add</>}
            </button>
          </div>
        )
      })}
      {!isExpanded && hidden > 0 && (
        <button onClick={onToggleExpand} className="w-full text-xs text-amber-600 hover:text-amber-800 font-medium py-1.5 border border-dashed border-amber-200 rounded-lg hover:bg-amber-50 transition-all">
          Show {hidden} more →
        </button>
      )}
      {isExpanded && items.length > LIMIT && (
        <button onClick={onToggleExpand} className="w-full text-xs text-gray-400 hover:text-gray-600 font-medium py-1">Show less</button>
      )}
    </div>
  )
}

function ChatGettingAroundSection({ data, selections, onSelect, isExpanded, onToggleExpand }) {
  if (!data?.options?.length) return <p className="text-xs text-gray-500">No transport info available</p>
  const LIMIT = 8
  const selectedTransport = selections?.getting_around || []
  const items = data.options
  const visible = isExpanded ? items : items.slice(0, LIMIT)
  const hidden = items.length - LIMIT
  return (
    <div className="space-y-1.5">
      {visible.map((opt, i) => {
        const isSelected = selectedTransport.some(a => a.name === opt.name)
        return (
        <div key={i} className={`border rounded-lg p-2 text-xs transition-all ${isSelected ? 'border-cyan-400 ring-1 ring-cyan-300 bg-cyan-50' : 'border-gray-200'}`}>
          <div className="flex items-center justify-between gap-1.5">
            <div className="flex items-center gap-1.5 min-w-0">
              <span className="font-medium text-gray-900">{opt.name}</span>
              <span className={`px-1 py-0.5 rounded text-[10px] font-medium shrink-0 ${opt.scope === 'intra_city' ? 'bg-cyan-100 text-cyan-700' : 'bg-indigo-100 text-indigo-700'}`}>{opt.type?.replace(/_/g, ' ')}</span>
            </div>
            <button type="button" onClick={() => onSelect('getting_around', opt)}
              className={`flex items-center gap-0.5 px-2 py-0.5 rounded-full text-[10px] font-semibold transition-all shrink-0 ${isSelected ? 'bg-cyan-600 text-white' : 'bg-gray-100 text-gray-500 hover:bg-cyan-100 hover:text-cyan-700'}`}>
              {isSelected ? <><Check size={8}/> Added</> : <><Plus size={8}/> Add</>}
            </button>
          </div>
          {opt.price_info && <p className="text-gray-500 mt-0.5">{opt.price_info}</p>}
          {opt.tips && <p className="text-gray-400 italic mt-0.5">{opt.tips.slice(0, 100)}{opt.tips.length > 100 ? '...' : ''}</p>}
          {opt.booking_url && <a href={opt.booking_url} target="_blank" rel="noopener noreferrer" className="text-cyan-600 hover:text-cyan-800 font-medium flex items-center gap-0.5 mt-0.5"><ExternalLink size={8} /> Info</a>}
        </div>
        )
      })}
      {!isExpanded && hidden > 0 && (
        <button onClick={onToggleExpand} className="w-full text-xs text-cyan-600 hover:text-cyan-800 font-medium py-1.5 border border-dashed border-cyan-200 rounded-lg hover:bg-cyan-50 transition-all">
          Show {hidden} more →
        </button>
      )}
      {isExpanded && items.length > LIMIT && (
        <button onClick={onToggleExpand} className="w-full text-xs text-gray-400 hover:text-gray-600 font-medium py-1">Show less</button>
      )}
    </div>
  )
}

function ChatForexSection({ data }) {
  if (!data || data.error || (!data?.local_currency && !data?.exchange_rates?.length)) return <p className="text-xs text-gray-500">No forex info available</p>
  const isHome = (rate) => rate.from_currency !== 'USD' && rate.from_currency !== 'EUR'
  return (
    <div className="space-y-2">
      {data.local_currency && (
        <div className="bg-emerald-50 border border-emerald-200 rounded-lg p-2">
          <p className="text-xs font-bold text-emerald-800 flex items-center gap-1">
            <DollarSign size={11} /> {data.local_currency.name} ({data.local_currency.code}) {data.local_currency.symbol}
          </p>
          {data.exchange_rates?.map((rate, i) => (
            <div key={i} className={`flex items-baseline gap-2 mt-1 ${isHome(rate) ? 'bg-amber-50 rounded px-1 py-0.5' : ''}`}>
              {isHome(rate) && <span className="text-[9px] font-semibold text-amber-600">YOUR</span>}
              {rate.rate != null
                ? <span className={`text-sm font-bold ${isHome(rate) ? 'text-amber-700' : 'text-emerald-700'}`}>{rate.rate}</span>
                : <span className="text-[10px] text-gray-400 flex items-center gap-0.5"><Loader2 size={9} className="animate-spin" /> Loading...</span>
              }
              <span className="text-[11px] text-gray-500">{rate.description}</span>
            </div>
          ))}
        </div>
      )}
      {data.exchange_locations?.length > 0 && (
        <div className="space-y-1">
          {data.exchange_locations.slice(0, 4).map((loc, i) => (
            <div key={i} className="border border-gray-200 rounded-lg p-2 text-xs">
              <div className="flex items-center gap-1.5">
                <span className="font-medium text-gray-900">{loc.name}</span>
                {loc.rating && <span className={`px-1 py-0.5 rounded text-[10px] font-medium ${
                  loc.rating === 'excellent' ? 'bg-emerald-100 text-emerald-700' :
                  loc.rating === 'good' ? 'bg-blue-100 text-blue-700' : 'bg-gray-100 text-gray-600'
                }`}>{loc.rating}</span>}
              </div>
              {loc.description && <p className="text-gray-500 mt-0.5">{loc.description.slice(0, 120)}{loc.description.length > 120 ? '...' : ''}</p>}
              {loc.fees && <p className="text-gray-400 mt-0.5">Fees: {loc.fees}</p>}
            </div>
          ))}
        </div>
      )}
      <div className="grid grid-cols-2 gap-2">
        {data.card_acceptance && (
          <div className="bg-sky-50 border border-sky-100 rounded-lg p-2 text-xs">
            <p className="font-semibold text-sky-800 mb-1">Cards</p>
            {data.card_acceptance.visa_mastercard && <p className="text-gray-600">{data.card_acceptance.visa_mastercard.slice(0, 80)}</p>}
          </div>
        )}
        {data.cash_advice && (
          <div className="bg-amber-50 border border-amber-100 rounded-lg p-2 text-xs">
            <p className="font-semibold text-amber-800 mb-1">Cash</p>
            {data.cash_advice.cash_dependency && <span className={`inline-block px-1 py-0.5 rounded text-[10px] font-medium ${
              data.cash_advice.cash_dependency === 'high' ? 'bg-red-100 text-red-700' :
              data.cash_advice.cash_dependency === 'medium' ? 'bg-yellow-100 text-yellow-700' : 'bg-green-100 text-green-700'
            }`}>{data.cash_advice.cash_dependency} dependency</span>}
          </div>
        )}
      </div>
      {data.tipping && (
        <p className={`text-xs rounded-lg p-2 border ${data.tipping.expected ? 'bg-amber-50 border-amber-200' : 'bg-green-50 border-green-200'}`}>
          <span className="font-semibold">{data.tipping.expected ? 'Tipping expected' : 'Tipping not expected'}</span>
          {data.tipping.description && <span className="text-gray-600"> — {data.tipping.description.slice(0, 100)}</span>}
        </p>
      )}
    </div>
  )
}

function ChatItinerarySection({ data, selections, onSelect }) {
  if (!data?.days?.length) return <p className="text-xs text-gray-500">No itinerary available</p>
  const selectedSlots = selections?.itinerary_slots || []
  return (
    <div className="space-y-2">
      {data.days.map(day => (
        <div key={day.day_number} className="border border-gray-200 rounded-lg overflow-hidden">
          <div className="bg-teal-600 text-white px-3 py-1.5 text-xs font-semibold flex justify-between">
            <span>Day {day.day_number} {day.date && `— ${day.date}`}</span>
            {day.theme && <span className="font-normal opacity-80">{day.theme}</span>}
          </div>
          <div className="divide-y divide-gray-100">
            {day.slots?.map((slot, j) => {
              const key = `${day.day_number}-${slot.time_of_day}`
              const isSelected = selectedSlots.some(s => s.key === key)
              const slotObj = { key, day_number: day.day_number, time_of_day: slot.time_of_day, activity: slot.activity, location: slot.location || '', estimated_cost_usd: slot.estimated_cost_usd }
              return (
                <div key={j} className="px-3 py-1.5 text-xs flex items-center gap-2">
                  <span className="text-gray-400 capitalize w-16 shrink-0">{slot.time_of_day}</span>
                  <div className="flex-1 min-w-0">
                    <p className="font-medium text-gray-900">{slot.activity}</p>
                    {slot.location && <p className="text-gray-500">{slot.location}</p>}
                  </div>
                  {slot.estimated_cost_usd != null && <span className="text-gray-400 shrink-0">${slot.estimated_cost_usd}</span>}
                  <button onClick={() => onSelect('itinerary_slots', slotObj)}
                    className={`px-2 py-0.5 rounded-full text-[10px] font-semibold shrink-0 ${isSelected ? 'bg-teal-600 text-white' : 'bg-gray-100 text-gray-500 hover:bg-teal-100'}`}>
                    {isSelected ? <><Check size={8}/> Added</> : <><Plus size={8}/> Add</>}
                  </button>
                </div>
              )
            })}
          </div>
        </div>
      ))}
    </div>
  )
}

// ─── Section wrapper with collapsible header ─────────────────────────────────

function ChatSection({ section, data, status, selections, onSelect }) {
  const [open, setOpen] = useState(true)
  const [isExpanded, setIsExpanded] = useState(false)
  const cfg = AGENT_CONFIG[section]
  if (!cfg) return null
  const Icon = cfg.icon
  const cc = CHAT_COLORS[cfg.color] || CHAT_COLORS.teal
  const toggleExpand = () => setIsExpanded(v => !v)

  const renderers = {
    flights:        () => <ChatFlightsSection data={data} selections={selections} onSelect={onSelect} isExpanded={isExpanded} onToggleExpand={toggleExpand} />,
    hotels:         () => <ChatHotelsSection data={data} selections={selections} onSelect={onSelect} isExpanded={isExpanded} onToggleExpand={toggleExpand} />,
    activities:     () => <ChatActivitiesSection data={data} selections={selections} onSelect={onSelect} isExpanded={isExpanded} onToggleExpand={toggleExpand} />,
    visa:           () => <ChatVisaSection data={data} />,
    sim:            () => <ChatSimSection data={data} selections={selections} onSelect={onSelect} isExpanded={isExpanded} onToggleExpand={toggleExpand} />,
    tips:           () => <ChatTipsSection data={data} selections={selections} onSelect={onSelect} isExpanded={isExpanded} onToggleExpand={toggleExpand} />,
    getting_around: () => <ChatGettingAroundSection data={data} selections={selections} onSelect={onSelect} isExpanded={isExpanded} onToggleExpand={toggleExpand} />,
    forex:          () => <ChatForexSection data={data} />,
    itinerary:      () => <ChatItinerarySection data={data} selections={selections} onSelect={onSelect} />,
  }

  return (
    <div className="border border-gray-200 rounded-xl overflow-hidden mb-2">
      <button onClick={() => setOpen(v => !v)}
        className={`flex items-center gap-2 px-3 py-2 w-full text-left ${cc.bg} border-b ${cc.border} ${cc.text} font-semibold text-xs`}>
        <Icon size={13} />
        <span className="flex-1">{cfg.label}</span>
        {status === 'enhancing' && <Loader2 size={10} className="animate-spin text-amber-500" />}
        {status === 'done' && <CheckCircle2 size={10} className="text-green-600" />}
        {open ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
      </button>
      {open && (
        <div className="p-3">
          {data ? (renderers[section] ? renderers[section]() : <pre className="text-xs">{JSON.stringify(data, null, 2)}</pre>) : <Loader2 size={14} className="animate-spin text-gray-400" />}
        </div>
      )}
    </div>
  )
}

// ─── Planning message with streamed sections ─────────────────────────────────

function PlanningMessage({ sections, sectionStatuses, selections, onSelect }) {
  const sectionOrder = ['flights', 'hotels', 'activities', 'visa', 'sim', 'tips', 'getting_around', 'forex', 'itinerary']
  const arrived = sectionOrder.filter(s => sections[s])
  const total = 9
  const doneCount = Object.values(sectionStatuses).filter(s => s === 'done' || s === 'enhancing').length

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 mb-3">
        <div className="flex-1 bg-gray-200 rounded-full h-1 overflow-hidden">
          <div className="bg-gradient-to-r from-teal-400 to-sky-400 h-full rounded-full transition-all duration-500" style={{ width: `${(doneCount / total) * 100}%` }} />
        </div>
        <span className="text-[10px] text-gray-400 shrink-0">{doneCount}/{total}</span>
      </div>
      {arrived.map(section => (
        <ChatSection key={section} section={section} data={sections[section]} status={sectionStatuses[section] || 'done'} selections={selections} onSelect={onSelect} />
      ))}
    </div>
  )
}

// ─── My Plan Drawer (compact version for chat) ──────────────────────────────

function ChatPlanDrawer({ isOpen, onClose, selections, planName, onPlanNameChange, onRemoveSelection, token, loadedPlanId, onLoadPlan, onClearLoadedPlan, onClearSelections }) {
  const [saving, setSaving] = useState(false)
  const [saveMsg, setSaveMsg] = useState('')
  const [savedPlans, setSavedPlans] = useState([])
  const [loadingPlans, setLoadingPlans] = useState(false)
  const [deletingId, setDeletingId] = useState(null)
  const [viewingPlan, setViewingPlan] = useState(null)
  const [isDragOver, setIsDragOver] = useState(false)
  const [isDragOverSaved, setIsDragOverSaved] = useState(false)

  const selectedCount = countSelections(selections)
  const estimatedCost = computePlanCost(selections)
  const budget = getBudgetStatus(estimatedCost, null)

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
    if (!token) { setSaveMsg('Please log in'); return }
    setSaving(true); setSaveMsg('')
    try {
      const isUpdate = !!loadedPlanId
      const url = isUpdate ? `/api/plans/${loadedPlanId}` : '/api/plans'
      const method = isUpdate ? 'PUT' : 'POST'
      const body = isUpdate
        ? JSON.stringify({ name: planName, selections })
        : JSON.stringify({ name: planName, search_data: {}, selections })
      const res = await fetch(url, { method, headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` }, body })
      if (res.ok) { setSaveMsg(isUpdate ? 'Plan updated!' : 'Saved!'); loadPlans(); setTimeout(() => setSaveMsg(''), 3000) }
      else setSaveMsg('Save failed')
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
    if (!token) { setSaveMsg('Please log in'); return }
    setSaving(true); setSaveMsg('')
    try {
      const isUpdate = !!loadedPlanId
      const url = isUpdate ? `/api/plans/${loadedPlanId}` : '/api/plans'
      const method = isUpdate ? 'PUT' : 'POST'
      const body = isUpdate
        ? JSON.stringify({ name: planName, selections })
        : JSON.stringify({ name: planName, search_data: {}, selections })
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
      {isOpen && <div className="fixed inset-0 bg-black/30 z-40" onClick={onClose} />}
      <div className={`fixed top-0 right-0 h-full w-full max-w-sm bg-white shadow-2xl z-50 flex flex-col transform transition-transform duration-300 ${isOpen ? 'translate-x-0' : 'translate-x-full'}`}>
        <div className="px-4 py-3 bg-gradient-to-r from-slate-500 to-slate-600 text-white shrink-0">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Bookmark size={18} />
              <h2 className="font-semibold">My Plan</h2>
              {selectedCount > 0 && <span className="bg-white/30 text-white text-xs font-bold px-2 py-0.5 rounded-full">{selectedCount}</span>}
              {loadedPlanId && <span className="bg-amber-400/30 text-amber-100 text-[10px] font-medium px-1.5 py-0.5 rounded">Editing saved plan</span>}
            </div>
            <div className="flex items-center gap-3">
              {estimatedCost > 0 && <p className="font-bold text-sm">${estimatedCost.toLocaleString(undefined, { maximumFractionDigits: 0 })}</p>}
              <button onClick={onClose} className="text-white/80 hover:text-white"><X size={18} /></button>
            </div>
          </div>
          {budget && (
            <div className={`mt-1.5 text-xs font-medium px-2.5 py-1 rounded-md inline-flex items-center gap-1.5 ${budget.status === 'under' ? 'bg-green-500/20 text-green-200' : 'bg-red-500/20 text-red-200'}`}>
              <DollarSign size={11} />
              {budget.label}
            </div>
          )}
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-4">
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

          {selections.flight && (
            <div className="border border-sky-200 bg-sky-50 rounded-xl p-3">
              <div className="flex items-center justify-between mb-1">
                <div className="flex items-center gap-1.5 text-xs font-semibold text-sky-700 uppercase"><Plane size={11} /> Flight</div>
                <button onClick={() => onRemoveSelection('flight')} className="text-gray-400 hover:text-red-500"><X size={13} /></button>
              </div>
              {selections.flight.outbound ? (
                <>
                  <p className="text-xs text-gray-500 mb-0.5">Outbound: <span className="font-medium text-gray-700">{selections.flight.outbound.airline}</span>{selections.flight.outbound.flight_number && <span className="text-gray-400 ml-1">{selections.flight.outbound.flight_number}</span>} · {selections.flight.outbound.origin} → {selections.flight.outbound.destination}</p>
                  {selections.flight.return && <p className="text-xs text-gray-500 mb-0.5">Return: <span className="font-medium text-gray-700">{selections.flight.return.airline}</span>{selections.flight.return.flight_number && <span className="text-gray-400 ml-1">{selections.flight.return.flight_number}</span>} · {selections.flight.return.origin} → {selections.flight.return.destination}</p>}
                  <p className="text-xs font-semibold text-sky-700 mt-1">${selections.flight.price_usd?.toLocaleString()} {selections.flight.trip_type === 'round_trip' ? 'round-trip' : 'one-way'}</p>
                </>
              ) : (
                <>
                  <p className="text-sm font-medium">{selections.flight.outbound?.airline || selections.flight.airline}</p>
                  <p className="text-xs text-gray-500">${selections.flight.price_usd?.toLocaleString()}</p>
                </>
              )}
              {selections.flight.booking_url && <a href={selections.flight.booking_url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 text-xs text-sky-600 hover:text-sky-800 font-medium mt-1"><ExternalLink size={10} /> Book</a>}
            </div>
          )}

          {selections.hotel && (
            <div className="border border-violet-200 bg-violet-50 rounded-xl p-3">
              <div className="flex items-center justify-between mb-1">
                <div className="flex items-center gap-1.5 text-xs font-semibold text-violet-700 uppercase"><Hotel size={11} /> Hotel</div>
                <button onClick={() => onRemoveSelection('hotel')} className="text-gray-400 hover:text-red-500"><X size={13} /></button>
              </div>
              <p className="text-sm font-medium">{selections.hotel.name}</p>
              <p className="text-xs text-gray-500">${selections.hotel.price_per_night_usd?.toLocaleString()}/night{selections.hotel.total_price_usd ? ` · $${selections.hotel.total_price_usd.toLocaleString()} total` : ''}</p>
              {selections.hotel.booking_url && <a href={selections.hotel.booking_url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 text-xs text-violet-600 hover:text-violet-800 font-medium mt-1"><ExternalLink size={10} /> Book</a>}
            </div>
          )}

          {selections.activities.length > 0 && (
            <div className="border border-emerald-200 bg-emerald-50 rounded-xl p-3">
              <div className="text-xs font-semibold text-emerald-700 uppercase mb-2"><MapPin size={11} className="inline" /> Activities ({selections.activities.length})</div>
              {selections.activities.map((a, i) => (
                <div key={i} className="flex items-center justify-between text-xs py-1 border-b border-emerald-100 last:border-0">
                  <div className="flex-1 min-w-0 mr-2">
                    <p className="font-medium text-gray-800 truncate">{a.name}</p>
                    <div className="flex items-center gap-2 text-gray-500">
                      {a.price_usd != null && <span>${a.price_usd}</span>}
                      {a.duration_hours && <span>{a.duration_hours}h</span>}
                    </div>
                    {a.booking_url && <a href={a.booking_url} target="_blank" rel="noopener noreferrer" className="text-emerald-600 text-[10px]"><ExternalLink size={8} className="inline" /> Book</a>}
                  </div>
                  <button onClick={() => onRemoveSelection('activities', a)} className="text-gray-400 hover:text-red-500 shrink-0"><X size={12} /></button>
                </div>
              ))}
            </div>
          )}

          {selections.sim && (
            <div className="border border-rose-200 bg-rose-50 rounded-xl p-3">
              <div className="flex items-center justify-between mb-1">
                <div className="flex items-center gap-1.5 text-xs font-semibold text-rose-700 uppercase"><Smartphone size={11} /> SIM</div>
                <button onClick={() => onRemoveSelection('sim')} className="text-gray-400 hover:text-red-500"><X size={13} /></button>
              </div>
              <p className="text-sm font-medium">{selections.sim.provider}</p>
              <p className="text-xs text-gray-500">{selections.sim.plan_name} · ${selections.sim.price_usd}</p>
              {selections.sim.url && <a href={selections.sim.url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 text-xs text-rose-600 hover:text-rose-800 font-medium mt-1"><ExternalLink size={10} /> Get</a>}
            </div>
          )}

          {selections.getting_around?.length > 0 && (
            <div className="border border-cyan-200 bg-cyan-50 rounded-xl p-3">
              <div className="text-xs font-semibold text-cyan-700 uppercase mb-2"><Bus size={11} className="inline" /> Getting Around ({selections.getting_around.length})</div>
              {selections.getting_around.map((opt, i) => (
                <div key={i} className="flex items-start justify-between text-xs py-1 border-b border-cyan-100 last:border-0">
                  <div className="flex-1 min-w-0 mr-2">
                    <p className="font-medium text-gray-800 truncate">{opt.name}</p>
                    <div className="flex items-center gap-2 mt-0.5 text-gray-500">
                      {opt.type && <span className="capitalize">{opt.type.replace(/_/g, ' ')}</span>}
                      {opt.scope && <span className="capitalize">{opt.scope.replace(/_/g, ' ')}</span>}
                    </div>
                    {opt.booking_url && <a href={opt.booking_url} target="_blank" rel="noopener noreferrer" className="text-cyan-600 text-[10px]"><ExternalLink size={8} className="inline" /> Info</a>}
                  </div>
                  <button onClick={() => onRemoveSelection('getting_around', opt)} className="text-gray-400 hover:text-red-500 shrink-0"><X size={12} /></button>
                </div>
              ))}
            </div>
          )}

          {selections.tips?.length > 0 && (
            <div className="border border-amber-200 bg-amber-50 rounded-xl p-3">
              <div className="text-xs font-semibold text-amber-700 uppercase mb-2"><Lightbulb size={11} className="inline" /> Tips ({selections.tips.length})</div>
              {selections.tips.map((t, i) => (
                <div key={i} className="flex items-center justify-between text-xs py-1 border-b border-amber-100 last:border-0">
                  <p className="font-medium text-gray-800 truncate flex-1 mr-2">{t.title}</p>
                  <button onClick={() => onRemoveSelection('tips', t)} className="text-gray-400 hover:text-red-500 shrink-0"><X size={12} /></button>
                </div>
              ))}
            </div>
          )}

          {selections.itinerary_slots?.length > 0 && (
            <div className="border border-teal-200 bg-teal-50 rounded-xl p-3">
              <div className="text-xs font-semibold text-teal-700 uppercase mb-2 flex items-center gap-1.5"><Calendar size={11} /> Itinerary ({selections.itinerary_slots.length} slots)</div>
              {selections.itinerary_slots.map((slot, i) => (
                <div key={i} className="flex items-start justify-between text-xs py-1 border-b border-teal-100 last:border-0">
                  <div className="flex-1 min-w-0 mr-2">
                    <p className="font-medium text-gray-800 truncate">{slot.activity}</p>
                    <p className="text-teal-500">Day {slot.day_number} · {slot.time_of_day}</p>
                  </div>
                  <button onClick={() => onRemoveSelection('itinerary_slots', slot)} className="text-gray-400 hover:text-red-500 shrink-0"><X size={12} /></button>
                </div>
              ))}
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
                    <p className="text-sm">Select items from search results<br />to build your plan</p>
                    <p className="text-xs mt-2 text-gray-300">or drag a saved plan here</p>
                  </>
              }
            </div>
          )}

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
            {loadingPlans && <p className="text-xs text-gray-400 text-center py-2">Loading…</p>}
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
                          <p className="text-xs text-gray-400">{plan.created_at?.slice(0, 10)}</p>
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
                      <button onClick={() => setViewingPlan(plan)}
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

      {viewingPlan && (
        <PlanViewModal
          plan={viewingPlan}
          token={token}
          onClose={() => setViewingPlan(null)}
          onSaved={(updated) => setViewingPlan(updated)}
          onDeleted={() => setViewingPlan(null)}
        />
      )}
    </>
  )
}

// ─── Suggestions ─────────────────────────────────────────────────────────────

const SUGGESTIONS = [
  "Plan a 5-day trip to Tokyo on a $2000 budget",
  "What do I need for a visa to Thailand as a US citizen?",
  "Find me cheap flights from NYC to Paris in June",
  "Suggest a romantic getaway in Europe for a week",
]

// ─── Suggestion chips after planning ────────────────────────────────────────

function SuggestionsBar({ chips, onSelect }) {
  if (!chips?.length) return null
  return (
    <div className="flex flex-wrap gap-1.5 mt-2 pt-2 border-t border-gray-100">
      {chips.map((chip, i) => (
        <button key={i} onClick={() => onSelect(chip)}
          className="px-3 py-1 text-xs font-medium text-teal-700 bg-teal-50 border border-teal-200 rounded-full hover:bg-teal-100 hover:border-teal-300 transition-all active:scale-95">
          {chip}
        </button>
      ))}
    </div>
  )
}

// ─── Real-time budget tracker ────────────────────────────────────────────────

function BudgetTracker({ selections, searchContext }) {
  const budget = searchContext?.budget_usd
  if (!budget || budget <= 0) return null
  const cost = computePlanCost(selections, searchContext)
  if (cost <= 0) return null
  const budgetStatus = getBudgetStatus(cost, budget)
  const pct = Math.min((cost / budget) * 100, 100)
  const barColor = budgetStatus?.status === 'over' ? 'bg-red-500' : pct >= 80 ? 'bg-amber-400' : 'bg-emerald-400'
  const textColor = budgetStatus?.status === 'over' ? 'text-red-700' : pct >= 80 ? 'text-amber-700' : 'text-emerald-700'
  return (
    <div className="mb-2 bg-white border border-gray-200 rounded-xl px-3 py-2 shadow-sm">
      <div className="flex items-center justify-between text-xs mb-1.5">
        <span className="text-gray-500 font-medium">Plan Cost</span>
        <span className={`font-bold ${textColor}`}>
          ${cost.toLocaleString(undefined, { maximumFractionDigits: 0 })}
          <span className="text-gray-400 font-normal">{' / '}${budget.toLocaleString(undefined, { maximumFractionDigits: 0 })}</span>
        </span>
      </div>
      <div className="w-full bg-gray-100 rounded-full h-1.5 overflow-hidden">
        <div className={`h-full rounded-full transition-all duration-500 ${barColor}`} style={{ width: `${pct}%` }} />
      </div>
      {budgetStatus?.status === 'over' && (
        <p className="text-[10px] text-red-600 mt-1">{budgetStatus.label}</p>
      )}
    </div>
  )
}

// ─── Message actions (copy + retry) ─────────────────────────────────────────

function MessageActions({ content, onRetry, isError }) {
  const [copied, setCopied] = useState(false)
  const handleCopy = async () => {
    await navigator.clipboard.writeText(content)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }
  return (
    <div className="flex gap-1.5 mt-1 opacity-0 group-hover:opacity-100 transition-opacity">
      <button onClick={handleCopy}
        className="flex items-center gap-1 text-[10px] text-gray-400 hover:text-gray-600 px-1.5 py-0.5 rounded hover:bg-gray-100">
        {copied ? <Check size={10} /> : <Copy size={10} />}
        {copied ? 'Copied' : 'Copy'}
      </button>
      {isError && onRetry && (
        <button onClick={onRetry}
          className="flex items-center gap-1 text-[10px] text-red-400 hover:text-red-600 px-1.5 py-0.5 rounded hover:bg-red-50">
          <RefreshCw size={10} /> Retry
        </button>
      )}
    </div>
  )
}

// ─── Main ChatPage ───────────────────────────────────────────────────────────

export default function ChatPage() {
  const { user, token } = useAuth()
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [isPlanOpen, setIsPlanOpen] = useState(false)
  const [planName, setPlanName] = useState('My Trip Plan')
  const [loadedPlanId, setLoadedPlanId] = useState(null)
  const [selections, setSelections] = useState({
    flight: null, hotel: null, activities: [], sim: null, tips: [], getting_around: [],
    itinerary_notes: {}, itinerary_edits: {}, itinerary_slots: [],
  })
  const [sessionContext, setSessionContext] = useState({})
  const [lastSearchContext, setLastSearchContext] = useState(null)
  const prevCountRef = useRef(0)
  const stopRef = useRef(null)
  const messagesEndRef = useRef(null)
  const inputRef = useRef(null)

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [])

  useEffect(() => { scrollToBottom() }, [messages, scrollToBottom])
  useEffect(() => { inputRef.current?.focus() }, [])

  // Restore chat history from localStorage on mount
  useEffect(() => {
    const key = `chat_history_${user?.username || 'guest'}`
    try {
      const raw = localStorage.getItem(key)
      if (!raw) return
      const parsed = JSON.parse(raw)
      if (parsed?.messages?.length > 0) {
        setMessages(parsed.messages)
        if (parsed.sessionContext) setSessionContext(parsed.sessionContext)
        if (parsed.lastSearchContext) setLastSearchContext(parsed.lastSearchContext)
      }
    } catch { localStorage.removeItem(`chat_history_${user?.username || 'guest'}`) }
  }, [user?.username])

  // Save chat history to localStorage on change
  useEffect(() => {
    if (isStreaming || messages.length === 0) return
    const key = `chat_history_${user?.username || 'guest'}`
    const serializable = {
      messages: messages.slice(-50).map(m => ({
        role: m.role, content: m.content,
        sections: m.sections || {}, sectionStatuses: m.sectionStatuses || {},
        suggestions: m.suggestions || [], planning: m.planning || false,
        planningDone: m.planningDone || false, error: m.error || false,
      })),
      sessionContext,
      lastSearchContext,
    }
    try {
      localStorage.setItem(key, JSON.stringify(serializable))
    } catch (e) {
      if (e.name === 'QuotaExceededError') {
        try { localStorage.setItem(key, JSON.stringify({ ...serializable, messages: serializable.messages.slice(-20) })) }
        catch {}
      }
    }
  }, [messages, sessionContext, lastSearchContext, user?.username, isStreaming])

  useEffect(() => {
    const count = countSelections(selections)
    if (prevCountRef.current === 0 && count > 0 && !loadedPlanId) {
      setPlanName(generatePlanName(null, [], null))
    }
    prevCountRef.current = count
  }, [selections, loadedPlanId])

  const handleLoadPlan = (plan) => {
    setSelections({ ...EMPTY_SELECTIONS, ...(plan.selections || {}) })
    setPlanName(plan.name)
    setLoadedPlanId(plan.id)
  }

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
    } else if (type === 'itinerary_slots') {
      setSelections(s => {
        const already = (s.itinerary_slots || []).some(sl => sl.key === value.key)
        return { ...s, itinerary_slots: already ? s.itinerary_slots.filter(sl => sl.key !== value.key) : [...(s.itinerary_slots || []), value] }
      })
    } else {
      setSelections(s => ({ ...s, [type]: value }))
    }
  }

  const handleRemoveSelection = (type, value) => {
    if (type === 'activities') setSelections(s => ({ ...s, activities: s.activities.filter(a => a.name !== value.name) }))
    else if (type === 'tips') setSelections(s => ({ ...s, tips: s.tips.filter(t => t.title !== value.title) }))
    else if (type === 'getting_around') setSelections(s => ({ ...s, getting_around: s.getting_around.filter(a => a.name !== value.name) }))
    else if (type === 'itinerary_slots') setSelections(s => ({ ...s, itinerary_slots: (s.itinerary_slots || []).filter(sl => sl.key !== value.key) }))
    else setSelections(s => ({ ...s, [type]: null }))
  }

  const getLatestSearchResults = useCallback(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].sections && Object.keys(messages[i].sections).length > 0) {
        return messages[i].sections
      }
    }
    return {}
  }, [messages])

  const applyPlanAction = useCallback((event) => {
    const { action, field, data } = event
    if (action === 'clear') {
      if (field === 'all') {
        setSelections({ ...EMPTY_SELECTIONS })
      } else if (['activities', 'tips', 'getting_around', 'itinerary_slots'].includes(field)) {
        setSelections(s => ({ ...s, [field]: [] }))
      } else {
        setSelections(s => ({ ...s, [field]: null }))
      }
    } else if (action === 'set') {
      setSelections(s => ({ ...s, [field]: data }))
    } else if (action === 'add') {
      if (['activities', 'tips', 'getting_around', 'itinerary_slots'].includes(field)) {
        setSelections(s => {
          const arr = s[field] || []
          const idKey = field === 'tips' ? 'title' : field === 'itinerary_slots' ? 'key' : 'name'
          if (arr.some(item => item[idKey] === data[idKey])) return s
          return { ...s, [field]: [...arr, data] }
        })
      } else {
        setSelections(s => ({ ...s, [field]: data }))
      }
    } else if (action === 'remove') {
      if (['activities', 'tips', 'getting_around', 'itinerary_slots'].includes(field)) {
        setSelections(s => {
          const idKey = field === 'tips' ? 'title' : field === 'itinerary_slots' ? 'key' : 'name'
          return { ...s, [field]: (s[field] || []).filter(item => item[idKey] !== data[idKey]) }
        })
      } else {
        setSelections(s => ({ ...s, [field]: null }))
      }
    }
  }, [])

  const sendMessage = useCallback((text) => {
    if (!text.trim() || isStreaming) return
    track('chat_message_sent', 'chat')
    const userMsg = { role: 'user', content: text.trim() }
    const newMessages = [...messages, userMsg]
    setMessages(newMessages)
    setInput('')
    setIsStreaming(true)

    const assistantIdx = newMessages.length
    setMessages(prev => [...prev, { role: 'assistant', content: '', streaming: true, sections: {}, sectionStatuses: {} }])

    let fullText = ''
    let sections = {}
    let sectionStatuses = {}
    let isPlanning = false
    let planActionsReceived = false

    const cleanup = streamChat(
      newMessages,
      (event) => {
        if (event.type === 'planning_start') {
          isPlanning = true
          setMessages(prev => {
            const updated = [...prev]
            updated[assistantIdx] = { ...updated[assistantIdx], planning: true }
            return updated
          })
        } else if (event.type === 'section_result') {
          const isStatic = event.source === 'static'
          const hasError = event.data?.error
          const existingIsGood = sections[event.section] && !sections[event.section]?.error
          if (!(hasError && existingIsGood)) {
            sections = { ...sections, [event.section]: event.data }
          }
          sectionStatuses = { ...sectionStatuses, [event.section]: isStatic ? 'enhancing' : 'done' }
          setMessages(prev => {
            const updated = [...prev]
            updated[assistantIdx] = { ...updated[assistantIdx], sections: { ...sections }, sectionStatuses: { ...sectionStatuses } }
            return updated
          })
        } else if (event.type === 'plan_clear') {
          setSelections({ ...EMPTY_SELECTIONS })
        } else if (event.type === 'plan_action') {
          planActionsReceived = true
          applyPlanAction(event)
        } else if (event.type === 'plan_ready') {
          if (planActionsReceived) setIsPlanOpen(true)
        } else if (event.type === 'session_context_update') {
          setSessionContext(event.context)
        } else if (event.type === 'search_context') {
          setLastSearchContext(event.params)
        } else if (event.type === 'suggestions') {
          setMessages(prev => {
            const updated = [...prev]
            updated[assistantIdx] = { ...updated[assistantIdx], suggestions: event.chips }
            return updated
          })
        } else if (event.type === 'planning_done') {
          setMessages(prev => {
            const updated = [...prev]
            updated[assistantIdx] = { ...updated[assistantIdx], streaming: false, planningDone: true }
            return updated
          })
          setIsStreaming(false)
          stopRef.current = null
          inputRef.current?.focus()
        } else if (event.type === 'delta') {
          fullText += event.text
          setMessages(prev => {
            const updated = [...prev]
            updated[assistantIdx] = { ...updated[assistantIdx], content: fullText }
            return updated
          })
        } else if (event.type === 'message' || event.type === 'result') {
          if (event.text && !fullText) {
            fullText = event.text
            setMessages(prev => {
              const updated = [...prev]
              updated[assistantIdx] = { ...updated[assistantIdx], content: fullText }
              return updated
            })
          }
        } else if (event.type === 'done') {
          setMessages(prev => {
            const updated = [...prev]
            updated[assistantIdx] = { ...updated[assistantIdx], streaming: false }
            return updated
          })
          setIsStreaming(false)
          stopRef.current = null
          inputRef.current?.focus()
        }
      },
      () => {
        setMessages(prev => {
          const updated = [...prev]
          if (updated[assistantIdx]?.streaming) {
            updated[assistantIdx] = { ...updated[assistantIdx], streaming: false }
          }
          return updated
        })
        setIsStreaming(false)
        stopRef.current = null
        inputRef.current?.focus()
      },
      (error) => {
        setMessages(prev => {
          const updated = [...prev]
          updated[assistantIdx] = { role: 'assistant', content: `Sorry, something went wrong: ${error.message}`, error: true }
          return updated
        })
        setIsStreaming(false)
        stopRef.current = null
        inputRef.current?.focus()
      },
      token,
      selections,
      getLatestSearchResults(),
      sessionContext,
    )
    stopRef.current = cleanup
  }, [messages, isStreaming, token, sessionContext])

  const handleStop = () => {
    if (stopRef.current) {
      stopRef.current()
      stopRef.current = null
      setIsStreaming(false)
      setMessages(prev => prev.map(m => m.streaming ? { ...m, streaming: false, stopped: true } : m))
    }
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(input) }
  }

  const clearChat = () => {
    if (isStreaming) return
    setMessages([])
    setSessionContext({})
    setLastSearchContext(null)
    localStorage.removeItem(`chat_history_${user?.username || 'guest'}`)
    inputRef.current?.focus()
  }

  const isEmpty = messages.length === 0
  const selectedCount = countSelections(selections)

  return (
    <div className="flex flex-col h-[calc(100vh-3.5rem)] bg-gradient-to-br from-sky-50 via-white to-teal-50">
      <div className="flex-1 overflow-y-auto">
        {isEmpty ? (
          <div className="flex flex-col items-center justify-center h-full px-4">
            <div className="w-14 h-14 rounded-2xl bg-teal-600 flex items-center justify-center mb-5 shadow-lg">
              <Plane className="text-white" size={28} />
            </div>
            <h2 className="text-2xl font-bold text-slate-700 mb-2">Travel Planner Chat</h2>
            <p className="text-slate-500 mb-8 text-center max-w-md">
              Chat with your AI travel assistant. Ask for a full trip plan and results will stream in real-time with interactive cards.
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 max-w-xl w-full">
              {SUGGESTIONS.map((s, i) => (
                <button key={i} onClick={() => sendMessage(s)}
                  className="text-left px-4 py-3 rounded-xl border border-gray-200 bg-white hover:border-teal-300 hover:bg-teal-50 text-sm text-slate-600 transition-all shadow-sm hover:shadow-md">
                  {s}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="max-w-3xl mx-auto px-4 py-6 space-y-6">
            {messages.map((msg, i) => (
              <React.Fragment key={i}>
                <ChatBubble
                  message={msg}
                  userName={user?.name}
                  selections={selections}
                  onSelect={handleSelect}
                  onRetry={msg.error ? () => {
                    const prevUser = messages.slice(0, i).filter(m => m.role === 'user').at(-1)
                    if (prevUser) sendMessage(prevUser.content)
                  } : undefined}
                />
                {msg.role === 'assistant' && msg.suggestions?.length > 0 && !msg.streaming && (
                  <div className="flex justify-start ml-11">
                    <SuggestionsBar chips={msg.suggestions} onSelect={(chip) => sendMessage(chip)} />
                  </div>
                )}
              </React.Fragment>
            ))}
            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      <div className="border-t border-gray-200 bg-white/80 backdrop-blur-sm px-4 py-3">
        <div className="max-w-3xl mx-auto">
          <BudgetTracker selections={selections} searchContext={lastSearchContext} />
          {messages.length > 0 && !isStreaming && (
            <div className="flex justify-end mb-2">
              <button onClick={clearChat} className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-red-500"><Trash2 size={12} /> Clear chat</button>
            </div>
          )}
          <div className="flex items-end gap-2">
            <div className="flex-1 relative">
              <textarea ref={inputRef} value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={handleKeyDown}
                placeholder="Ask about your next trip..." rows={1} disabled={isStreaming}
                className="w-full resize-none px-4 py-3 pr-12 border border-gray-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-teal-400 text-sm bg-white max-h-36 overflow-y-auto"
                style={{ minHeight: '48px' }}
                onInput={(e) => { e.target.style.height = 'auto'; e.target.style.height = Math.min(e.target.scrollHeight, 144) + 'px' }} />
            </div>
            {isStreaming ? (
              <button onClick={handleStop} className="flex-shrink-0 w-11 h-11 flex items-center justify-center rounded-xl bg-red-500 hover:bg-red-600 text-white shadow-sm" title="Stop">
                <Square size={16} fill="white" />
              </button>
            ) : (
              <button onClick={() => sendMessage(input)} disabled={!input.trim()}
                className="flex-shrink-0 w-11 h-11 flex items-center justify-center rounded-xl bg-teal-600 hover:bg-teal-700 disabled:bg-gray-200 disabled:text-gray-400 text-white shadow-sm" title="Send">
                <Send size={16} />
              </button>
            )}
          </div>
          <p className="text-[11px] text-slate-400 mt-2 text-center">AI-powered travel assistant. Verify important details with official sources.</p>
        </div>
      </div>

      {/* My Plan floating button */}
      {(() => { const cost = computePlanCost(selections); return (
      <button onClick={() => setIsPlanOpen(true)}
        className="fixed bottom-20 right-6 z-40 flex items-center gap-2 px-3 py-2.5 bg-teal-600 text-white font-semibold rounded-full shadow-xl hover:shadow-2xl hover:bg-teal-700 transition-all">
        <Bookmark size={14} />
        <span className="text-xs">My Plan</span>
        {cost > 0 && <span className="text-[10px] font-bold opacity-80">${cost.toLocaleString(undefined, {maximumFractionDigits:0})}</span>}
        {selectedCount > 0 && <span className="bg-white text-teal-700 text-[10px] font-bold w-4 h-4 rounded-full flex items-center justify-center">{selectedCount}</span>}
      </button>
      )})()}

      <ChatPlanDrawer
        isOpen={isPlanOpen}
        onClose={() => setIsPlanOpen(false)}
        selections={selections}
        planName={planName}
        onPlanNameChange={setPlanName}
        onRemoveSelection={handleRemoveSelection}
        token={token}
        loadedPlanId={loadedPlanId}
        onLoadPlan={handleLoadPlan}
        onClearLoadedPlan={() => setLoadedPlanId(null)}
        onClearSelections={() => setSelections({ ...EMPTY_SELECTIONS })}
      />
    </div>
  )
}

// ─── Chat Bubble ─────────────────────────────────────────────────────────────

function ChatBubble({ message, userName, selections, onSelect, onRetry }) {
  const isUser = message.role === 'user'
  const isError = message.error
  const hasSections = message.planning || Object.keys(message.sections || {}).length > 0

  return (
    <div className={`flex gap-3 ${isUser ? 'justify-end' : 'justify-start'}`}>
      {!isUser && (
        <div className="flex-shrink-0 w-8 h-8 rounded-lg bg-teal-600 flex items-center justify-center mt-0.5">
          <Plane className="text-white" size={16} />
        </div>
      )}
      <div className={`group max-w-[85%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${
        isUser ? 'bg-teal-600 text-white rounded-br-md'
        : isError ? 'bg-red-50 text-red-700 border border-red-200 rounded-bl-md'
        : 'bg-white text-slate-700 shadow-sm border border-gray-100 rounded-bl-md'
      }`}>
        {isUser ? (
          <p className="whitespace-pre-wrap">{message.content}</p>
        ) : hasSections ? (
          <div>
            {message.planning && !message.planningDone && Object.keys(message.sections || {}).length === 0 && (
              <div className="flex items-center gap-2 text-sm text-teal-700 mb-2">
                <Loader2 size={14} className="animate-spin" /> Searching for your trip details...
              </div>
            )}
            {Object.keys(message.sections || {}).length > 0 && (
              <PlanningMessage
                sections={message.sections}
                sectionStatuses={message.sectionStatuses || {}}
                selections={selections}
                onSelect={onSelect}
              />
            )}
            {message.content && <div className="mt-3"><MarkdownContent text={message.content} /></div>}
          </div>
        ) : (
          <MarkdownContent text={message.content} />
        )}
        {message.streaming && !hasSections && (
          <span className="inline-block w-1.5 h-4 bg-teal-500 rounded-sm ml-0.5 animate-pulse align-text-bottom" />
        )}
        {!isUser && !message.streaming && message.content && (
          <MessageActions content={message.content} onRetry={onRetry} isError={isError} />
        )}
      </div>
      {isUser && (
        <div className="flex-shrink-0 w-8 h-8 rounded-lg bg-slate-200 flex items-center justify-center mt-0.5">
          <User className="text-slate-500" size={16} />
        </div>
      )}
    </div>
  )
}

// ─── Markdown renderer ───────────────────────────────────────────────────────

function MarkdownContent({ text }) {
  if (!text) return null
  // Ensure headings are always separated from following content by a blank line,
  // otherwise the block regex captures only the heading and silently drops the rest.
  const normalized = text.replace(/^(#{1,6} [^\n]+)\n(?!\n)/gm, '$1\n\n')
  const rawBlocks = normalized.split(/\n\n+/)
  return (
    <div className="space-y-2 prose-sm">
      {rawBlocks.map((block, i) => {
        const h3Match = block.match(/^### (.+)/)
        if (h3Match) return <h4 key={i} className="font-semibold text-slate-800 text-sm mt-1"><InlineMarkdown text={h3Match[1]} /></h4>
        const h2Match = block.match(/^## (.+)/)
        if (h2Match) return <h3 key={i} className="font-bold text-slate-800 text-base mt-2"><InlineMarkdown text={h2Match[1]} /></h3>
        const h1Match = block.match(/^# (.+)/)
        if (h1Match) return <h2 key={i} className="font-bold text-slate-800 text-lg mt-2"><InlineMarkdown text={h1Match[1]} /></h2>
        if (/^---+$/.test(block.trim())) return <hr key={i} className="border-gray-200 my-2" />
        const lines = block.split('\n')
        const tableLines = lines.filter(l => l.trim().startsWith('|'))
        if (tableLines.length >= 2) return <MarkdownTable key={i} lines={tableLines} />
        if (lines.every(l => /^[\s]*[-*] /.test(l) || l.trim() === '')) {
          return <ul key={i} className="list-disc list-inside space-y-1">{lines.filter(l => l.trim()).map((l, j) => <li key={j}><InlineMarkdown text={l.replace(/^[\s]*[-*] /, '')} /></li>)}</ul>
        }
        if (lines.every(l => /^[\s]*\d+[.)]\s/.test(l) || l.trim() === '')) {
          return <ol key={i} className="list-decimal list-inside space-y-1">{lines.filter(l => l.trim()).map((l, j) => <li key={j}><InlineMarkdown text={l.replace(/^[\s]*\d+[.)]\s/, '')} /></li>)}</ol>
        }
        return <p key={i} className="whitespace-pre-wrap"><InlineMarkdown text={block} /></p>
      })}
    </div>
  )
}

function MarkdownTable({ lines }) {
  const parseRow = (line) => line.split('|').slice(1, -1).map(cell => cell.trim())
  const isSeparator = (line) => /^\|[\s-:|]+\|$/.test(line.trim())
  const headers = parseRow(lines[0])
  const dataLines = lines.filter((l, idx) => idx > 0 && !isSeparator(l))
  return (
    <div className="overflow-x-auto my-2">
      <table className="min-w-full text-xs border-collapse">
        <thead><tr className="bg-teal-50 border-b border-teal-200">{headers.map((h, i) => <th key={i} className="px-3 py-1.5 text-left font-semibold text-teal-800"><InlineMarkdown text={h} /></th>)}</tr></thead>
        <tbody>{dataLines.map((line, ri) => <tr key={ri} className={ri % 2 === 0 ? 'bg-white' : 'bg-gray-50'}>{parseRow(line).map((cell, ci) => <td key={ci} className="px-3 py-1.5 border-b border-gray-100"><InlineMarkdown text={cell} /></td>)}</tr>)}</tbody>
      </table>
    </div>
  )
}

function InlineMarkdown({ text }) {
  const parts = text.split(/(\*\*.*?\*\*|`[^`]+`|\*[^*]+\*|\[([^\]]+)\]\(([^)]+)\))/g)
  const elements = []
  for (let i = 0; i < parts.length; i++) {
    const part = parts[i]
    if (!part) continue
    const linkMatch = part.match(/^\[([^\]]+)\]\(([^)]+)\)$/)
    if (linkMatch) { elements.push(<a key={i} href={linkMatch[2]} target="_blank" rel="noopener noreferrer" className="text-teal-600 hover:text-teal-800 underline underline-offset-2">{linkMatch[1]}</a>); i += 2; continue }
    if (part.startsWith('**') && part.endsWith('**')) elements.push(<strong key={i} className="font-semibold">{part.slice(2, -2)}</strong>)
    else if (part.startsWith('`') && part.endsWith('`')) elements.push(<code key={i} className="bg-gray-100 text-teal-700 px-1 py-0.5 rounded text-xs">{part.slice(1, -1)}</code>)
    else if (part.startsWith('*') && part.endsWith('*') && !part.startsWith('**')) elements.push(<em key={i}>{part.slice(1, -1)}</em>)
    else elements.push(<span key={i}>{part}</span>)
  }
  return <>{elements}</>
}
