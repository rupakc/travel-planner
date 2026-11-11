import { Info } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { formatPrice } from '../../../utils/priceWatch'
import { estimateCount, liveCount, rowPrice, totalDifference, tripRows } from '../../../utils/tripWatch'
import TripBadge from '../TripBadge'

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
  const { t } = useTranslation('alerts')
  if (!watch) {
    const parts = preview.parts || []
    return (
      <div className="mt-3 rounded-xl bg-slate-50 px-4 py-3">
        <p className="text-sm font-medium text-slate-700">{t('trip.yourPlan')}</p>
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
          {t('trip.lookup')} {t('trip.estimatesNote')}
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
            {t('trip.caption', { live, count: estimates })}
          </caption>
          <thead className="sr-only">
            <tr><th scope="col">{t('trip.part')}</th><th scope="col">{t('trip.price')}</th><th scope="col">{t('trip.kind')}</th></tr>
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
                  {r.in_total === false && <span className="block text-[10px] text-slate-500">{t('trip.notInTotal')}</span>}
                </td>
                <td className="py-1 text-right"><TripBadge row={r} /></td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr className="border-t border-emerald-200 font-semibold">
              <th scope="row" className="pt-1.5 pr-2 text-left">{t('trip.total')}</th>
              <td className="pt-1.5 pr-2 text-right tabular-nums">{formatPrice(total)}</td>
              <td />
            </tr>
          </tfoot>
        </table>
      </div>
      {diff && (
        <p data-testid="trip-total-diff" className="mt-2 text-xs text-slate-600">
          {t(diff.delta < 0 ? 'trip.diffLess' : 'trip.diffMore', {
            amount: formatPrice(Math.abs(diff.delta)),
            plan: formatPrice(diff.plan),
            tail: diff.reasons.length ? `: ${diff.reasons.join('; ')}.` : '.',
          })}
        </p>
      )}
      <Note>{t('trip.estimatesNote')} {t('trip.alertsNote')}</Note>
    </div>
  )
}
