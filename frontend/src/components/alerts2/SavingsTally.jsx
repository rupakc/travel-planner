import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Share2 } from 'lucide-react'
import { useAuth } from '../../context/AuthContext'
import { getSavings } from '../../services/alertsApi'
import { fmtCurrency } from '../../i18n/format'
import { prefersReducedMotion } from './PriceChart'
import SavingsShareCard from './SavingsShareCard'

const MILESTONES = [50, 200, 1000]
const R = 34
const CIRC = 2 * Math.PI * R

// Counts from 0 to `target` with requestAnimationFrame; reduced motion jumps
// straight to the final value.
function useCountUp(target) {
  const [v, setV] = useState(() => (prefersReducedMotion() ? target : 0))
  useEffect(() => {
    if (prefersReducedMotion()) { setV(target); return undefined }
    let raf; const start = performance.now(); const dur = 700
    const step = (now) => {
      const p = Math.min(1, (now - start) / dur)
      setV(target * (1 - (1 - p) ** 3))
      if (p < 1) raf = requestAnimationFrame(step)
    }
    raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf)
  }, [target])
  return v
}

const isEmpty = (s) => !s || (!(s.drops_caught > 0) && !(s.total_usd > 0) && !Object.keys(s.by_currency || {}).length)

/**
 * Savings tally of /alerts/summary: a count-up of caught USD drops, other
 * currencies as separate chips (never converted), a ring to the next milestone,
 * counters, the best catch and a Share button. `compact` is one line for the
 * header. Pass `savings` to render a ready object, otherwise it loads one.
 */
export default function SavingsTally({ savings: given = null, compact = false }) {
  const { t } = useTranslation('savings')
  const { token } = useAuth()
  const [loaded, setLoaded] = useState(null)
  const [sharing, setSharing] = useState(false)
  const savings = given || loaded
  useEffect(() => {
    if (given || !token) return undefined
    let live = true
    getSavings(token).then((s) => { if (live) setLoaded(s) }, () => {})
    return () => { live = false }
  }, [given, token])

  const usd = savings?.total_usd > 0 ? savings.total_usd : 0
  const shown = useCountUp(usd)
  if (!savings) return null

  if (isEmpty(savings)) {
    return (
      <p className={compact ? 'text-xs text-slate-500 dark:text-slate-400' : 'rounded-xl border border-slate-200 p-4 text-sm text-slate-600 dark:border-slate-700 dark:text-slate-300'}
        data-testid="savings-empty">
        {t('empty')}
        {!compact && <span className="mt-1 block text-xs text-slate-500 dark:text-slate-400">{t('emptyHint')}</span>}
      </p>
    )
  }

  const chips = Object.entries(savings.by_currency || {}).filter(([, v]) => v > 0)
  if (compact) {
    return (
      <p className="text-xs text-slate-600 dark:text-slate-300" data-testid="savings-compact">
        {usd > 0 && <span className="font-semibold tabular-nums">{t('amountLine', { amount: fmtCurrency(usd, 'USD') })}</span>}
        {usd > 0 && ' · '}
        {t('drops', { count: savings.drops_caught || 0 })}
        {chips.map(([cur, v]) => <span key={cur}>{' · '}{fmtCurrency(v, cur)}</span>)}
      </p>
    )
  }

  const pct = Math.max(0, Math.min(100, savings.progress_pct ?? 0))
  const next = savings.next_milestone
  const best = savings.best && savings.best.caught > 0 ? savings.best : null
  return (
    <section className="space-y-3 rounded-xl border border-slate-200 p-4 dark:border-slate-700" aria-label={t('title')} data-testid="savings-tally">
      <div className="flex items-center gap-4">
        <svg viewBox="0 0 80 80" className="h-20 w-20 shrink-0" role="img" data-testid="savings-ring" data-progress={pct}
          aria-label={next ? t('progress', { pct, amount: fmtCurrency(next, 'USD') }) : t('allDone')}>
          <circle cx="40" cy="40" r={R} fill="none" strokeWidth="8" className="stroke-slate-200 dark:stroke-slate-700" />
          <circle cx="40" cy="40" r={R} fill="none" strokeWidth="8" strokeLinecap="round" transform="rotate(-90 40 40)"
            className="stroke-teal-700 dark:stroke-teal-400" strokeDasharray={CIRC}
            strokeDashoffset={CIRC * (1 - (next ? pct : 100) / 100)} />
          <text x="40" y="45" textAnchor="middle" className="fill-slate-700 text-[14px] font-semibold dark:fill-slate-100">{next ? `${pct}%` : '✓'}</text>
        </svg>
        <div className="min-w-0 space-y-1">
          <p className="text-lg font-bold tabular-nums text-slate-900 dark:text-slate-50" data-testid="savings-total">
            {t('amountLine', { amount: fmtCurrency(Math.round(shown), 'USD') })}
          </p>
          <p className="text-xs text-slate-600 dark:text-slate-300">
            {t('drops', { count: savings.drops_caught || 0 })}
            {savings.targets_hit > 0 && <> · {t('targets', { count: savings.targets_hit })}</>}
          </p>
          <p className="text-xs text-slate-500 dark:text-slate-400" data-testid="savings-ring-label">
            {next ? t('progress', { pct, amount: fmtCurrency(next, 'USD') }) : t('allDone')}
          </p>
        </div>
      </div>

      {chips.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5" data-testid="savings-chips" aria-label={t('otherCurrencies')}>
          {chips.map(([cur, v]) => (
            <span key={cur} className="rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-medium tabular-nums text-slate-700 dark:bg-slate-800 dark:text-slate-200">
              {fmtCurrency(v, cur)}
            </span>
          ))}
        </div>
      )}

      <ul className="flex flex-wrap gap-2" aria-label={t('milestones')}>
        {MILESTONES.map((m) => {
          const hit = (savings.total_usd || 0) >= m
          return (
            <li key={m} data-testid="milestone-tick" data-reached={hit}
              className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${hit ? 'bg-teal-700 text-white' : 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300'}`}>
              {hit ? t('milestoneReached', { amount: fmtCurrency(m, 'USD') }) : t('milestoneAhead', { amount: fmtCurrency(m, 'USD') })}
            </li>
          )
        })}
      </ul>

      {best && (
        <p className="text-sm text-slate-700 dark:text-slate-200" data-testid="savings-best">
          {best.title
            ? t('best', { title: best.title, amount: fmtCurrency(best.caught, best.currency || 'USD') })
            : t('bestNoTitle', { amount: fmtCurrency(best.caught, best.currency || 'USD') })}
        </p>
      )}
      <p className="text-xs text-slate-500 dark:text-slate-400">{t('caveat')}</p>

      <button type="button" data-tid="savings-share" onClick={() => setSharing(true)}
        className="inline-flex min-h-[44px] items-center gap-2 rounded-lg bg-teal-700 px-4 text-sm font-semibold text-white hover:bg-teal-800">
        <Share2 className="h-4 w-4" aria-hidden="true" />{t('share')}
      </button>
      {sharing && <SavingsShareCard savings={savings} onClose={() => setSharing(false)} />}
    </section>
  )
}
