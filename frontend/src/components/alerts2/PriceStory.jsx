import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Minus, Sparkles, ThumbsUp, TrendingDown, TrendingUp } from 'lucide-react'
import { useAuth } from '../../context/AuthContext'
import { getStory, requestAdvice } from '../../services/alertsApi'
import { updateFareWatch, updatePriceWatch } from '../../services/api'
import { fmtCurrency } from '../../i18n/format'
import { adviceFor, stepFor } from '../../utils/alertStory'
import PriceChart from './PriceChart'
import TargetSlider from './TargetSlider'

const VERDICT_ICON = { great: TrendingDown, good: ThumbsUp, typical: Minus, high: TrendingUp }
const VERDICT_STYLE = {
  great: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200',
  good: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-200',
  typical: 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200',
  high: 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200',
}

// Params that are money are formatted with the watch currency; the rest are counts.
function adviceText(t, advice, currency) {
  const { code, params = {} } = advice
  const o = {}
  if (code === 'below_target') o.by = fmtCurrency(params.by, currency)
  else if (code === 'near_target') o.gap = fmtCurrency(params.gap, currency)
  else if (code === 'checks_paused' || code === 'steady') o.count = params.days
  else if (code === 'few_checks') o.count = params.n
  return t(`advice.${code}`, o)
}

/**
 * The price story of one watch (docs/Alerts-API.md). Pass `story` to render a
 * ready object, or `kind` + `watchId` to load it. Stale prices are labelled
 * with their age; the verdict is withheld when the server withholds it.
 */
export default function PriceStory({ kind, watchId, story: given = null, onTargetSaved }) {
  const { t } = useTranslation('priceStory')
  const { token } = useAuth()
  const [story, setStory] = useState(given)
  const [failed, setFailed] = useState(false)
  const [tip, setTip] = useState(null)
  const [tipState, setTipState] = useState('idle')
  const [saved, setSaved] = useState(null)

  useEffect(() => { if (given) setStory(given) }, [given])
  useEffect(() => {
    if (given || !token) return undefined
    let live = true
    getStory(token, kind, watchId).then((s) => { if (live) setStory(s) }, () => { if (live) setFailed(true) })
    return () => { live = false }
  }, [given, token, kind, watchId])

  const commit = useCallback(async (value) => {
    const id = story?.watch_id ?? watchId
    const changes = { target_price: value, alert_mode: 'below_target' }
    try {
      if ((story?.kind ?? kind) === 'flight') await updateFareWatch(id, changes, token)
      else await updatePriceWatch(id, changes, token)
      setStory((s) => (s ? { ...s, target: value, mode: 'below_target' } : s))
      setSaved('ok')
      onTargetSaved?.(value)
    } catch { setSaved('error') }
  }, [story, kind, watchId, token, onTargetSaved])

  const getTip = async () => {
    setTipState('loading')
    try {
      const r = await requestAdvice(token, story.kind, story.watch_id)
      setTip(r.tip); setTipState('idle')
    } catch (e) {
      setTipState(e?.code === 'ai_limit' || e?.error_code === 'ai_limit' ? 'limit' : 'error')
    }
  }

  if (failed) return <p className="text-sm text-slate-500">{t('error.load')}</p>
  if (!story) return <p className="text-sm text-slate-500" role="status">{t('loading')}</p>

  const { currency, points = [], typical, verdict, estimate } = story
  const advice = story.advice || adviceFor(story)
  const days = story.checked_days_ago
  const Icon = verdict ? VERDICT_ICON[verdict] : null
  const prices = points.map((p) => p.price)
  const lo = prices.length ? Math.min(...prices) : 0
  const hi = prices.length ? Math.max(...prices, story.target ?? 0) : 0
  const sliderMin = Math.floor(lo * 0.5)
  const sliderMax = Math.ceil(Math.max(hi, story.baseline ?? 0) * 1.1)
  const step = Math.max(1, Math.round(stepFor(story.kind, hi || 1) / 5))

  return (
    <section className="space-y-3" aria-label={t('title')}>
      <div className="flex flex-wrap items-center gap-2">
        {verdict && Icon && (
          <span data-testid="verdict-chip" aria-label={t('verdictLabel', { level: t(`verdict.${verdict}`) })}
            className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-semibold ${VERDICT_STYLE[verdict]}`}>
            <Icon className="h-3.5 w-3.5" aria-hidden="true" />
            {t(`verdict.${verdict}`)}
          </span>
        )}
        {story.latest && (
          <span className="text-sm font-semibold tabular-nums" title={t('latest')}>{fmtCurrency(story.latest.price, currency)}</span>
        )}
        {days != null && (
          <span className="text-xs text-slate-500 dark:text-slate-400">
            {days === 0 ? t('checkedToday') : t('checkedAgo', { count: days })}
          </span>
        )}
      </div>

      <p className="text-sm text-slate-700 dark:text-slate-200" data-testid="advice">{adviceText(t, advice, currency)}</p>

      {estimate && (
        <p className="text-xs italic text-slate-500 dark:text-slate-400" data-testid="estimate">
          {t('estimate', { price: fmtCurrency(estimate.price, currency) })}
        </p>
      )}

      {points.length >= 2 ? (
        <PriceChart points={points} typical={typical} target={story.target} baseline={story.baseline}
          lowest={story.lowest?.price} currency={currency} />
      ) : (
        <p className="text-xs text-slate-500 dark:text-slate-400" data-testid="few-checks">
          {points.length === 0 ? t('chart.none') : t('chart.few', { count: points.length })}
        </p>
      )}

      {points.length >= 2 && (
        <TargetSlider min={sliderMin} max={sliderMax} step={step} currency={currency}
          value={story.target ?? story.latest?.price ?? sliderMax} points={points} onCommit={commit} />
      )}
      {saved && (
        <p className="text-xs text-slate-500" role="status">{saved === 'ok' ? t('slider.saved') : t('slider.error')}</p>
      )}

      {story.kind === 'flight' && (
        <div className="space-y-1">
          <button type="button" onClick={getTip} disabled={tipState === 'loading'}
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50 disabled:opacity-60 dark:border-slate-600 dark:hover:bg-slate-800">
            <Sparkles className="h-4 w-4" aria-hidden="true" />
            {tipState === 'loading' ? t('tip.loading') : t('tip.button')}
            <span className="text-[10px] uppercase tracking-wide text-slate-500">{t('tip.ai')}</span>
          </button>
          {tip && <p className="text-sm text-slate-700 dark:text-slate-200" data-testid="tip"><strong>{t('tip.title')}: </strong>{tip}</p>}
          {tipState === 'error' && <p className="text-xs text-red-600" role="alert">{t('tip.error')}</p>}
          {tipState === 'limit' && <p className="text-xs text-red-600" role="alert">{t('tip.limit')}</p>}
        </div>
      )}
    </section>
  )
}
