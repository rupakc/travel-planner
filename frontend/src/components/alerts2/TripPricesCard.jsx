import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAlerts } from '../../context/AlertsContext'
import { useAlertsV2 } from '../../hooks/useAlertsV2'
import { getStory } from '../../services/alertsApi'
import { listFareWatches, listPriceWatches } from '../../services/api'
import { fmtCurrency } from '../../i18n/format'
import { routeLabel } from '../../utils/fareWatch'
import { priceWatchLink } from '../../utils/priceWatch'
import WatchSuggestions from './WatchSuggestions'

const VERDICT_STYLE = {
  great: 'bg-emerald-100 text-emerald-800',
  good: 'bg-emerald-50 text-emerald-700',
  typical: 'bg-slate-100 text-slate-700',
  high: 'bg-amber-100 text-amber-800',
}
const MAX_STORIES = 6
const asList = (r) => (Array.isArray(r) ? r : Array.isArray(r?.watches) ? r.watches : [])
const titleOf = (w) => (w.kind === 'flight' ? routeLabel(w)
  : w.title || w.subject?.name || w.subject?.title || w.subject?.city || '')

/**
 * The trip overview's "Prices" card (price alerts 2.0): the watches made for
 * this plan (`plan_id`), each with its verdict chip, a link to the alerts hub
 * and "Watch prices for this trip", which opens the suggestions on demand.
 */
export default function TripPricesCard({ planId, token }) {
  const { t } = useTranslation('quickWatch')
  const { t: tp } = useTranslation('priceStory')
  const { on, livePrices } = useAlertsV2()
  const { watchVersion } = useAlerts()
  const [rows, setRows] = useState(null)
  const [failed, setFailed] = useState(false)
  const [suggest, setSuggest] = useState(false)

  useEffect(() => {
    if (!on || !token || planId == null) return undefined
    let cancelled = false
    ;(async () => {
      try {
        const [fares, prices] = await Promise.all([listFareWatches(token), listPriceWatches(token)])
        const mine = [
          ...asList(fares).map((w) => ({ ...w, kind: 'flight' })),
          ...asList(prices),
        ].filter((w) => w.plan_id === planId && w.status !== 'expired')
        if (cancelled) return
        setRows(mine.map((w) => ({ w, story: null })))
        setFailed(false)
        // Verdict chips load after the list shows, for the first few watches only
        const stories = await Promise.allSettled(mine.slice(0, MAX_STORIES).map((w) => getStory(token, w.kind, w.id)))
        if (cancelled) return
        setRows(mine.map((w, i) => ({ w, story: stories[i]?.status === 'fulfilled' ? stories[i].value : null })))
      } catch {
        if (!cancelled) setFailed(true)
      }
    })()
    return () => { cancelled = true }
  }, [on, token, planId, watchVersion])

  if (!on) return null
  return (
    <section data-tid="trip.prices" aria-labelledby="trip-prices-title"
      className="rounded-2xl border border-white/60 bg-white/80 p-4 shadow-sm">
      <h3 id="trip-prices-title" className="text-sm font-semibold text-gray-900">{t('prices.title')}</h3>
      {failed && <p role="alert" className="mt-2 text-sm text-red-700">{t('prices.loadFailed')}</p>}
      {rows && !failed && (rows.length === 0
        ? <p data-tid="trip.prices.empty" className="mt-2 text-sm text-gray-600">{t('prices.empty')}</p>
        : (
          <ul className="mt-2 space-y-2">
            {rows.map(({ w, story }) => (
              <li key={`${w.kind}:${w.id}`} className="flex flex-wrap items-center justify-between gap-2 text-sm">
                <Link to={w.kind === 'flight' ? `/alerts?watch=${w.id}` : priceWatchLink(w)} data-tid="trip.prices.watch"
                  className="min-w-0 truncate font-medium text-teal-800 hover:underline">{titleOf(w)}</Link>
                <span className="flex items-center gap-2">
                  {w.last_price != null && <span className="tabular-nums text-gray-700">{fmtCurrency(w.last_price, w.currency || 'USD')}</span>}
                  {story?.verdict && VERDICT_STYLE[story.verdict] && (
                    <span data-tid="trip.prices.verdict" className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${VERDICT_STYLE[story.verdict]}`}>
                      {tp(`verdict.${story.verdict}`)}
                    </span>
                  )}
                  {!story?.verdict && (story?.pending_first_check ?? w.pending_first_check) && (
                    <span className="text-xs text-gray-500">{t('prices.pending')}</span>
                  )}
                </span>
              </li>
            ))}
          </ul>
        ))}
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <Link to="/alerts" data-tid="trip.prices.hub"
          className="inline-flex min-h-[44px] items-center text-sm font-medium text-teal-800 hover:underline">{t('prices.hub')}</Link>
        {livePrices && (
          <button type="button" data-tid="trip.prices.suggest" onClick={() => setSuggest(true)}
            className="inline-flex min-h-[44px] items-center rounded-lg border border-teal-700 px-3 text-sm font-medium text-teal-800 hover:bg-teal-50">
            {t('prices.watchTrip')}
          </button>
        )}
      </div>
      {suggest && <WatchSuggestions planId={planId} force onDone={() => setSuggest(false)} />}
    </section>
  )
}
