import { Info } from 'lucide-react'
import { formatPrice } from '../../../utils/priceWatch'
import { estimateCount, liveCount, rowPrice, totalDifference, tripRows } from '../../../utils/tripWatch'
import TripBadge from '../TripBadge'

const ESTIMATES_NOTE = 'Estimates are fixed and never trigger alerts.'

function Note({ children }) {
  return (
    <p className="mt-2 flex items-start gap-1.5 text-xs text-slate-500">
      <Info size={12} className="mt-0.5 shrink-0" aria-hidden="true" /> <span>{children}</span>
    </p>
  )
}

/**
 * Trip body of the price-watch dialog. Before watching: what the plan costs
 * now, by category (`preview.parts`), and how live prices are found. Once
 * watched: each part with its price and a Live / Estimate badge, and the
 * total being watched.
 */
export default function TripDialogBody({ preview = {}, watch = null }) {
  if (!watch) {
    const parts = preview.parts || []
    return (
      <div className="mt-3 rounded-xl bg-slate-50 px-4 py-3">
        <p className="text-sm font-medium text-slate-700">Your plan, as we’ll count it</p>
        {parts.length > 0 && (
          <ul className="mt-1.5 space-y-1 text-xs text-slate-600">
            {parts.map(p => (
              <li key={p.key} className="flex justify-between gap-3">
                <span>
                  {p.label}
                  {p.note && <span className="block text-[11px] text-slate-500">{p.note}</span>}
                </span>
                <span className="tabular-nums">{formatPrice(p.amount)}</span>
              </li>
            ))}
          </ul>
        )}
        <Note>
          When you start, we look up live prices for your flight (the cheapest fare on your dates, not one
          specific flight), hotel and up to 5 activities, and show the live total. Anything without a live
          price stays at its estimate. {ESTIMATES_NOTE}
        </Note>
      </div>
    )
  }

  const rows = tripRows(watch)
  const diff = totalDifference(watch, preview.planTotal)
  const total = watch.last_price ?? watch.baseline_price
  const live = liveCount(rows)
  const estimates = estimateCount(rows)
  return (
    <div className="text-sm text-slate-700">
      <div className="-mx-1 overflow-x-auto px-1">
        <table className="w-full min-w-[16rem] text-left text-xs">
          <caption className="mb-1 text-left text-xs font-medium text-slate-600">
            What we’re watching · {live} live, {estimates} estimate{estimates === 1 ? '' : 's'}
          </caption>
          <thead className="sr-only">
            <tr><th scope="col">Part</th><th scope="col">Price</th><th scope="col">Kind</th></tr>
          </thead>
          <tbody>
            {rows.map(r => (
              <tr key={r.id} className="border-t border-emerald-100/80 first:border-t-0">
                <th scope="row" className="py-1 pr-2 font-normal">
                  {r.label}
                  {r.detail && <span className="block text-[10px] text-slate-500">{r.detail}</span>}
                </th>
                <td className="py-1 pr-2 text-right tabular-nums">
                  {rowPrice(r)}
                  {r.in_total === false && <span className="block text-[10px] text-slate-500">not in total</span>}
                </td>
                <td className="py-1 text-right"><TripBadge row={r} /></td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr className="border-t border-emerald-200 font-semibold">
              <th scope="row" className="pt-1.5 pr-2 text-left">Total</th>
              <td className="pt-1.5 pr-2 text-right tabular-nums">{formatPrice(total)}</td>
              <td />
            </tr>
          </tfoot>
        </table>
      </div>
      {diff && (
        <p data-testid="trip-total-diff" className="mt-2 text-xs text-slate-600">
          That’s {formatPrice(Math.abs(diff.delta))} {diff.delta < 0 ? 'less' : 'more'} than your My Plan total
          ({formatPrice(diff.plan)}){diff.reasons.length ? `: ${diff.reasons.join('; ')}.` : '.'}
        </p>
      )}
      <Note>{ESTIMATES_NOTE} Alerts come only from live prices moving the total by at least $25 or 4 %.</Note>
    </div>
  )
}
