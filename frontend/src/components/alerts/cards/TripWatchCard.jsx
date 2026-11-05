import { useNavigate } from 'react-router-dom'
import { Route } from 'lucide-react'
import { useAuth } from '../../../context/AuthContext'
import { useSearchData } from '../../../context/SearchDataContext'
import { replanSearchData } from '../../../utils/fareWatch'
import { track } from '../../../utils/analytics'
import {
  groupTotals, percent, rowPrice, tripReplanFare, tripRows, whatChanged,
} from '../../../utils/tripWatch'
import TripBadge from '../TripBadge'
import PriceWatchCard from './PriceWatchCard'

/** Flights / stay / activities / other as one stacked bar (USD parts). */
function BreakdownBar({ rows }) {
  const groups = groupTotals(rows)
  if (!groups.length) return null
  return (
    <div className="mt-3">
      <div data-testid="trip-bar" role="img" aria-label={groups.map(g => `${g.label} ${percent(g.share)}`).join(', ')}
        className="flex h-2.5 gap-px overflow-hidden rounded-full bg-slate-100">
        {groups.map(g => (
          <div key={g.key} data-group={g.key} className={`${g.color} motion-safe:transition-[width] motion-safe:duration-500`}
            style={{ width: `${g.share * 100}%` }} />
        ))}
      </div>
      <ul className="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-slate-500" aria-hidden="true">
        {groups.map(g => (
          <li key={g.key} className="inline-flex items-center gap-1">
            <span className={`h-2 w-2 rounded-full ${g.color}`} />{g.label} {percent(g.share)}
          </li>
        ))}
      </ul>
    </div>
  )
}

function TripDetails({ watch }) {
  const navigate = useNavigate()
  const { preferences } = useAuth()
  const { setPendingSearchData } = useSearchData()
  const rows = tripRows(watch)
  const changed = whatChanged(watch)
  const fare = tripReplanFare(watch)
  const past = watch.status === 'expired'

  const replan = () => {
    track('watch_replanned', 'alerts', { kind: 'trip' })
    setPendingSearchData(replanSearchData(fare, preferences))
    navigate('/')
  }

  return (
    <>
      <BreakdownBar rows={rows} />
      {rows.length > 0 && (
        <ul aria-label="Trip price breakdown" className="mt-3 divide-y divide-slate-100 rounded-xl border border-slate-100 text-sm">
          {rows.map(r => (
            <li key={r.id} className="flex items-center gap-2 px-3 py-1.5">
              <span className="min-w-0 flex-1 truncate text-slate-700" title={r.label}>{r.label}</span>
              <TripBadge row={r} />
              <span className="w-20 shrink-0 text-right tabular-nums text-slate-800">
                {rowPrice(r)}
                {r.in_total === false && <span className="block text-[10px] text-slate-400">not in total</span>}
              </span>
            </li>
          ))}
        </ul>
      )}
      {rows.some(r => !r.live) && (
        <p className="mt-1.5 text-[11px] text-slate-500">Estimates are fixed and never trigger alerts.</p>
      )}
      {changed && <p className="mt-2 text-xs text-slate-600">{changed}</p>}
      {!past && fare && (
        <button type="button" onClick={replan}
          className="mt-3 inline-flex items-center gap-1.5 rounded-full border border-sky-300 bg-white px-3 py-1.5 text-xs font-semibold text-sky-700 hover:bg-sky-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-500">
          <Route size={13} aria-hidden="true" /> Re-plan this trip
        </button>
      )}
    </>
  )
}

/** A watched whole trip: the shared card plus its breakdown, badges and "what changed". */
export default function TripWatchCard(props) {
  return <PriceWatchCard {...props} Details={TripDetails} openLabel="Open" />
}
