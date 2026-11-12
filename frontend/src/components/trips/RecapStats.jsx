import { useTranslation } from 'react-i18next'
import { fmtNumber, fmtCurrency } from '../../i18n/format'

function Tile({ label, value, tid, note }) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-3 dark:border-gray-700 dark:bg-gray-800" data-tid={tid}>
      <div className="text-xl font-bold text-gray-900 dark:text-gray-100">{value}</div>
      <div className="text-xs text-gray-600 dark:text-gray-300">{label}</div>
      {note ? <div className="text-[11px] text-gray-500 dark:text-gray-400">{note}</div> : null}
    </div>
  )
}

export function Stats({ recap, plannedKm }) {
  const { t } = useTranslation('recap')
  const km = recap.distance_km ?? plannedKm
  const planned = recap.distance_km == null && plannedKm != null
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3" data-tid="recap.stats">
      <Tile tid="recap.stat-days" label={t('stats.days')} value={fmtNumber(recap.days ?? 0)} />
      <Tile tid="recap.stat-places" label={t('stats.places')} value={fmtNumber(recap.visited_count ?? 0)} />
      <Tile tid="recap.stat-distance" label={t('stats.distance')}
        value={km == null ? '–' : t('stats.km', { km: fmtNumber(km) })} note={planned ? t('map.planned') : null} />
      <Tile tid="recap.stat-countries" label={t('stats.countries')} value={fmtNumber((recap.countries || []).length)} />
      <Tile tid="recap.stat-journal" label={t('stats.journal')} value={fmtNumber(recap.journal_count ?? 0)} />
      <Tile tid="recap.stat-stars" label={t('stats.stars')}
        value={recap.avg_stars == null ? '–' : fmtNumber(recap.avg_stars, { maximumFractionDigits: 1 })} />
    </div>
  )
}

const usd = (n) => fmtCurrency(n, 'USD')

export function Spend({ spend, planCost }) {
  const { t } = useTranslation('recap')
  if (!spend) return null
  const spent = spend.spent_usd == null ? null : Number(spend.spent_usd)
  const budget = Number(spend.budget_usd) > 0 ? Number(spend.budget_usd) : null
  const pct = spent != null && budget ? Math.min(100, Math.round((spent / budget) * 100)) : null
  return (
    <section className="rounded-xl border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-800" data-tid="recap.spend">
      <h3 className="font-semibold text-gray-900 dark:text-gray-100">{t('spend.title')}</h3>
      <dl className="mt-2 space-y-1 text-sm text-gray-800 dark:text-gray-200">
        <div className="flex justify-between"><dt>{t('spend.spent')}</dt><dd data-tid="recap.spent">{spent == null ? '–' : usd(spent)}</dd></div>
        {budget != null && <div className="flex justify-between"><dt>{t('spend.budget')}</dt><dd data-tid="recap.budget">{usd(budget)}</dd></div>}
        {planCost > 0 && <div className="flex justify-between"><dt>{t('spend.planned')}</dt><dd data-tid="recap.plan-cost">{usd(planCost)}</dd></div>}
      </dl>
      {pct != null && (
        <div className="mt-2 h-2 overflow-hidden rounded bg-gray-200 dark:bg-gray-700" role="progressbar"
          aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label={t('spend.title')}>
          <div className={`h-full ${spent > budget ? 'bg-amber-600' : 'bg-teal-700'}`} style={{ width: `${pct}%` }} />
        </div>
      )}
      <p className="mt-2 text-xs text-gray-600 dark:text-gray-300">{t('spend.estimateNote')}</p>
      {spend.unconverted?.length > 0 && (
        <p className="mt-1 text-xs text-amber-800 dark:text-amber-300" data-tid="recap.unconverted">
          {t('spend.unconverted', { currencies: spend.unconverted.join(', ') })}
        </p>
      )}
    </section>
  )
}
