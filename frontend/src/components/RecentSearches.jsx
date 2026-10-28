import { useState } from 'react'
import { ChevronDown, History as HistoryIcon, RotateCcw, Users, X } from 'lucide-react'
import { describeRecentSearch } from '../utils/recentSearches'

const MAX_INTEREST_CHIPS = 3

function RecentSearchCard({ entry, today, onLoad, onRerun, onRemove }) {
  const { route, dates, interests, travelers } = describeRecentSearch(entry.search)
  const datesPassed = entry.search.departure_date < today

  return (
    <li className="relative shrink-0 w-60 snap-start bg-white border border-gray-200 rounded-xl shadow-sm hover:border-teal-300 hover:shadow-md transition-all">
      <button type="button" onClick={() => onLoad(entry)}
        title="Load into the form to change anything before searching"
        className="w-full text-left p-3 pr-8 rounded-xl focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400">
        <p className="text-sm font-semibold text-gray-900 truncate">{route}</p>
        <p className="text-xs text-gray-500 mt-0.5">
          {dates}
          {datesPassed && <span className="ml-1.5 text-amber-600 font-medium">· dates passed</span>}
        </p>
        <div className="flex flex-wrap items-center gap-1 mt-2 min-h-[20px]">
          {interests.slice(0, MAX_INTEREST_CHIPS).map((i) => (
            <span key={i} className="px-1.5 py-0.5 bg-teal-50 text-teal-700 rounded text-[11px] capitalize">{i}</span>
          ))}
          {interests.length > MAX_INTEREST_CHIPS && (
            <span className="text-[11px] text-gray-400">+{interests.length - MAX_INTEREST_CHIPS}</span>
          )}
          <span className="ml-auto inline-flex items-center gap-0.5 text-[11px] text-gray-400"><Users size={10} />{travelers}</span>
        </div>
      </button>
      <div className="px-3 pb-2.5">
        <button type="button" onClick={() => onRerun(entry)} disabled={datesPassed}
          title={datesPassed ? 'These dates have passed — load it and pick new dates' : 'Run this exact search again'}
          className="inline-flex items-center gap-1 text-xs font-medium text-teal-600 hover:text-teal-800 disabled:text-gray-300 disabled:cursor-not-allowed transition-colors">
          <RotateCcw size={11} /> Search again
        </button>
      </div>
      <button type="button" onClick={() => onRemove(entry)} aria-label={`Remove recent search ${route}`}
        className="absolute top-2 right-2 p-1 rounded text-gray-300 hover:text-red-500 hover:bg-red-50 transition-colors">
        <X size={13} />
      </button>
    </li>
  )
}

// Whether the section is expanded is a per-browser convenience; storage can
// be blocked (private mode), in which case it simply starts open each time.
export const OPEN_STORAGE_KEY = 'tp_recent_searches_open'

const readOpen = () => {
  try { return localStorage.getItem(OPEN_STORAGE_KEY) !== 'false' } catch { return true }
}
const writeOpen = (open) => {
  try { localStorage.setItem(OPEN_STORAGE_KEY, String(open)) } catch { /* not persisted */ }
}

/** Collapsible strip of the user's recent searches shown above the Search form. */
export default function RecentSearches({ entries, today, onLoad, onRerun, onRemove }) {
  const [open, setOpen] = useState(readOpen)
  if (!entries?.length) return null

  const toggle = () => {
    setOpen(!open)
    writeOpen(!open)
  }

  return (
    <section className="mb-6">
      <h2>
        <button type="button" onClick={toggle} aria-expanded={open} aria-controls="recent-searches-list"
          className="w-full flex items-center gap-1.5 py-1 text-xs font-semibold text-gray-500 uppercase tracking-wide hover:text-gray-700 rounded focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400 transition-colors">
          <HistoryIcon size={12} /> Recent searches
          <span className="px-1.5 py-px rounded-full bg-gray-100 text-gray-500 text-[10px] font-semibold normal-case tracking-normal">{entries.length}</span>
          <ChevronDown size={14} aria-hidden="true"
            className={`ml-auto transition-transform duration-200 ${open ? 'rotate-180' : ''}`} />
        </button>
      </h2>
      {open && (
        <ul id="recent-searches-list" className="flex gap-3 overflow-x-auto snap-x pt-2 pb-2 -mx-1 px-1">
          {entries.map((entry) => (
            <RecentSearchCard key={entry.id} entry={entry} today={today}
              onLoad={onLoad} onRerun={onRerun} onRemove={onRemove} />
          ))}
        </ul>
      )}
    </section>
  )
}
