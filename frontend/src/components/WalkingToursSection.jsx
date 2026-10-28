import { useState } from 'react'
import { Star, Clock, Check, Plus, ExternalLink, MapPin, X } from 'lucide-react'
import { safeUrl } from '../utils/planPrint'

const LINK_REL = 'noopener noreferrer'
const cityName = (c) => String(c || '').split(',')[0].trim()

function CityChip({ city }) {
  if (!city) return null
  return (
    <span data-testid="city-chip" className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-full bg-indigo-50 text-indigo-600 border border-indigo-200 text-[10px] font-semibold whitespace-nowrap">
      <MapPin size={9} /> {cityName(city)}
    </span>
  )
}

function TourImage({ src }) {
  const [failed, setFailed] = useState(false)
  const safe = safeUrl(src)
  if (!safe || failed) return null
  return (
    <img src={safe} alt="" loading="lazy" referrerPolicy="no-referrer"
      onError={() => setFailed(true)}
      className="w-full h-32 object-cover rounded-lg mb-3" />
  )
}

function TourCard({ tour, isSelected, showCity, onSelect }) {
  const href = safeUrl(tour.url)
  const stop = e => e.stopPropagation()
  return (
    <div
      onClick={() => onSelect('walking_tours', tour)}
      className={`border rounded-xl p-4 cursor-pointer transition-all ${isSelected ? 'border-lime-400 ring-2 ring-lime-300 bg-lime-50' : 'border-gray-200 hover:shadow-md'}`}
    >
      <TourImage src={tour.image_url} />
      <div className="flex items-start justify-between mb-2 gap-2">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-sky-100 text-sky-700">{tour.provider}</span>
          {tour.top_pick && <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-amber-100 text-amber-700">Top pick</span>}
        </div>
        <button type="button" aria-label={`${isSelected ? 'Remove' : 'Add'} ${tour.name}`}
          onClick={e => { e.stopPropagation(); onSelect('walking_tours', tour) }}
          className={`flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-semibold transition-all shrink-0 ${isSelected ? 'bg-lime-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-lime-100 hover:text-lime-700'}`}>
          {isSelected ? <><Check size={11} /> Added</> : <><Plus size={11} /> Add</>}
        </button>
      </div>
      <h3 className="font-semibold text-gray-900 mb-1">
        {href
          ? <a href={href} target="_blank" rel={LINK_REL} onClick={stop} className="hover:underline">{tour.name}</a>
          : tour.name}
      </h3>
      <div className="flex flex-wrap items-center gap-3 text-xs text-gray-500 mb-1.5">
        {tour.rating != null && (
          <span className="text-amber-600 font-semibold flex items-center gap-0.5">
            <Star size={10} className="fill-amber-400 text-amber-400" />
            {Number(tour.rating).toFixed(1)}
            {tour.review_count ? <span className="text-gray-400 font-normal ml-0.5">({tour.review_count.toLocaleString('en-US')} reviews)</span> : null}
          </span>
        )}
        {tour.duration && <span className="flex items-center gap-1"><Clock size={10} />{tour.duration}</span>}
        {tour.price_note && <span className="text-green-600 font-medium">{tour.price_note}</span>}
      </div>
      {tour.reason && <p className="text-xs italic text-gray-600 mb-2">{tour.reason}</p>}
      <div className="flex flex-wrap items-center gap-1.5 mt-1.5">
        {showCity && <CityChip city={tour.city} />}
        {href && (
          <a href={href} target="_blank" rel={LINK_REL} onClick={stop}
            className="flex items-center gap-1 text-xs text-lime-600 hover:text-lime-700 font-medium">
            <ExternalLink size={10} /> View on {tour.provider} ↗
          </a>
        )}
      </div>
    </div>
  )
}

// Top picks first within each city; cities keep their incoming (journey) order.
function sortTopPicksPerCity(results) {
  const groups = new Map()
  for (const t of results) {
    const key = cityName(t.city)
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key).push(t)
  }
  return [...groups.values()].flatMap(group =>
    [...group].sort((a, b) => Number(!!b.top_pick) - Number(!!a.top_pick)))
}

function sourceLabel(s, multiCity) {
  const name = multiCity && s.city ? `${s.provider} · ${cityName(s.city)}` : s.provider
  if (s.status === 'error') return `${name} (unavailable)`
  if (s.status === 'none') return `${name} (0)`
  return `${name} (${s.count})`
}

// One selected walking tour in the My Plan drawer.
export function WalkingTourPlanRow({ tour, onRemove }) {
  const href = safeUrl(tour.url)
  return (
    <div className="flex items-start justify-between border-b border-teal-100 last:border-0 pb-1.5 last:pb-0">
      <div className="flex-1 min-w-0 mr-2">
        <p className="text-xs font-medium text-gray-800">{tour.name}</p>
        <div className="flex items-center gap-2 mt-0.5 text-xs text-gray-500">
          {tour.provider && <span>{tour.provider}</span>}
          {tour.city && <span className="truncate">{tour.city}</span>}
        </div>
        {href && (
          <a href={href} target="_blank" rel={LINK_REL} className="flex items-center gap-1 text-xs text-teal-600 hover:text-teal-800 font-medium mt-0.5"><ExternalLink size={9} /> Details</a>
        )}
      </div>
      <button type="button" aria-label={`Remove ${tour.name}`} onClick={() => onRemove(tour)} className="text-gray-400 hover:text-red-500 shrink-0 mt-0.5"><X size={12}/></button>
    </div>
  )
}

export default function WalkingToursSection({ data, selections, onSelect }) {
  if (data?.error) {
    return <div className="p-4 text-sm text-gray-500">Couldn't reach the walking-tour sites this time — the rest of your plan is unaffected.</div>
  }
  const results = data?.results || []
  if (!results.length) {
    return <div className="p-4 text-sm text-gray-500">No free walking tours listed for this destination on GuruWalk, FreeTour.com, SANDEMANs or FreeWalkingTour.com.</div>
  }
  const sorted = sortTopPicksPerCity(results)
  const showCity = new Set(results.map(t => cityName(t.city)).filter(Boolean)).size > 1
  const selected = selections?.walking_tours || []
  const sources = data?.sources || []
  const multiCitySources = showCity || new Set(sources.map(s => cityName(s.city)).filter(Boolean)).size > 1
  return (
    <div className="p-4">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {sorted.map((tour, i) => (
          <TourCard key={tour.id || tour.url || i} tour={tour} showCity={showCity}
            isSelected={selected.some(s => s.url === tour.url)} onSelect={onSelect} />
        ))}
      </div>
      {sources.length > 0 && (
        <p data-testid="walking-tours-sources" className="text-xs text-gray-400 mt-3">
          Searched:{' '}
          {sources.map((s, i) => {
            const href = s.status === 'ok' ? safeUrl(s.url) : null
            const label = sourceLabel(s, multiCitySources)
            return (
              <span key={`${s.provider_key}-${s.city}-${i}`}>
                {i > 0 && (multiCitySources ? ', ' : ' · ')}
                {href
                  ? <a href={href} target="_blank" rel={LINK_REL} className="hover:underline">{label}</a>
                  : label}
              </span>
            )
          })}
        </p>
      )}
    </div>
  )
}
