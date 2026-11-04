import { useState } from 'react'
import { Link2, X, Loader2, CheckCircle2 } from 'lucide-react'
import { linkCoverageSummary } from '../utils/linkImport'
import { safeUrl } from '../utils/planPrint'

/** Results banner for a trip imported from a link: how many of its places
 *  made it into the itinerary. */
export default function LinkPlanBanner({ searchData, itinerary }) {
  const [dismissed, setDismissed] = useState(false)
  const [showMissing, setShowMissing] = useState(false)
  const summary = linkCoverageSummary(searchData, itinerary)
  if (!summary || dismissed) return null
  const href = safeUrl(searchData.import_source?.url)
  const title = summary.title || 'your link'
  const source = href
    ? <a href={href} target="_blank" rel="noopener noreferrer" className="font-semibold italic underline decoration-amber-400 decoration-2 underline-offset-2 hover:decoration-amber-600">{title}</a>
    : <span className="font-semibold italic">{title}</span>
  const n = summary.total
  const all = !summary.pending && summary.inItinerary === n

  return (
    <div role="status" className="flex items-start gap-3 rounded-2xl bg-gradient-to-r from-amber-50 to-orange-50/70 p-3.5 ring-1 ring-amber-200 sm:p-4">
      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-amber-400 text-amber-950">
        {summary.pending ? <Loader2 size={17} className="animate-spin" /> : all ? <CheckCircle2 size={18} /> : <Link2 size={17} />}
      </span>
      <div className="min-w-0 flex-1 text-sm text-gray-800">
        <p>
          {summary.pending
            ? <>Fitting your {n} {n === 1 ? 'place' : 'places'} into the days — from {source}.</>
            : <>Planned around {n} {n === 1 ? 'place' : 'places'} from {source} — {all
              ? (n === 1 ? 'it’s in your itinerary.' : `all ${n} are in your itinerary.`)
              : <>{summary.inItinerary} of {n} are in your itinerary.{' '}
                <button type="button" onClick={() => setShowMissing((v) => !v)} aria-expanded={showMissing}
                  className="font-medium text-amber-800 underline underline-offset-2 hover:text-amber-950">
                  {summary.missing.length} didn’t fit{showMissing ? '' : ': show'}
                </button></>}</>}
        </p>
        {showMissing && summary.missing.length > 0 && (
          <p data-missing className="mt-1 text-xs text-gray-600">
            {summary.missing.join(', ')} — add a night, or move one in with the itinerary’s Edit button.
          </p>
        )}
        {!summary.pending && <p className="mt-0.5 text-xs text-amber-900/70">Look for the “From your link” tags below.</p>}
      </div>
      <button type="button" aria-label="Dismiss" onClick={() => setDismissed(true)}
        className="shrink-0 rounded-full p-1 text-amber-800/60 hover:bg-amber-100 hover:text-amber-900">
        <X size={15} />
      </button>
    </div>
  )
}
