import { useTranslation } from 'react-i18next'
import { bestByRow, fmtUsd, fmtDuration } from '../utils/compare'
import { track } from '../utils/analytics'

const DASH = '—'

// Backend Travel Ease grade (static_results.get_confidence_score) -> chip
const GRADES = {
  green: { cls: 'bg-emerald-50 text-emerald-700 border-emerald-200' },
  amber: { cls: 'bg-amber-50 text-amber-700 border-amber-200' },
  red: { cls: 'bg-red-50 text-red-700 border-red-200' },
}

const Badge = ({ children, tone = 'slate' }) => {
  const tones = {
    slate: 'bg-slate-100 text-slate-600 border-slate-200',
    amber: 'bg-amber-50 text-amber-700 border-amber-200',
    emerald: 'bg-emerald-50 text-emerald-700 border-emerald-200',
    red: 'bg-red-50 text-red-700 border-red-200',
  }
  return <span className={`ml-1.5 inline-block text-[10px] font-semibold px-1.5 py-0.5 rounded-full border ${tones[tone]}`}>{children}</span>
}

const Best = ({ t }) => <Badge tone="emerald">{t('compare.best')}</Badge>

const num = (v) => typeof v === 'number' && Number.isFinite(v)
const temp = (v) => (num(v) ? `${Math.round(v)}°` : DASH)

// Each row: key (matches bestByRow where numeric; its label is compare.row.<key>), render(summary, t) -> node | null
const ROWS = [
  {
    key: 'estimate',
    render: (s, t) => {
      const e = s.estimate
      if (!e || !num(e.total_usd)) return null
      return (
        <>
          <span className="font-semibold">{fmtUsd(e.total_usd)}</span>
          <Badge>{t('compare.estimate')}</Badge>
          {e.budget_status === 'under' && <Badge tone="emerald">{t('compare.underBudget')}</Badge>}
          {e.budget_status === 'over' && <Badge tone="red">{t('compare.overBudget')}</Badge>}
          {e.partial && <div className="text-xs text-slate-500 mt-0.5">{t('compare.partial')}</div>}
        </>
      )
    },
  },
  {
    key: 'flight',
    render: (s, t) => {
      const f = s.flight
      if (!f) return null
      const stops = !num(f.stops) ? null : f.stops === 0 ? t('compare.nonstop') : t('compare.stops', { count: f.stops })
      const dur = fmtDuration(f.duration_minutes)
      return (
        <>
          <span className="font-semibold">{fmtUsd(f.price_usd)}</span>
          {f.source === 'estimate' && <Badge tone="amber">{t('compare.estimate')}</Badge>}
          <div className="text-xs text-slate-500">{[stops, dur, f.airline].filter(Boolean).join(' · ')}</div>
        </>
      )
    },
  },
  {
    key: 'hotel',
    render: (s, t) => {
      const h = s.hotel
      if (!h) return null
      return (
        <>
          <span className="font-semibold">{fmtUsd(h.typical_nightly_usd)}</span> {t('compare.typical')}
          {num(h.cheapest_good_nightly_usd) && <div className="text-xs text-slate-500">{t('compare.fromWellReviewed', { amount: fmtUsd(h.cheapest_good_nightly_usd) })}</div>}
        </>
      )
    },
  },
  {
    key: 'weather',
    render: (s, t) => {
      const w = s.weather
      if (!w) return null
      return (
        <>
          <span className="font-semibold">{temp(w.avg_high_c)} / {temp(w.avg_low_c)}{num(w.avg_high_c) || num(w.avg_low_c) ? 'C' : ''}</span>
          {w.source !== 'open-meteo' && <Badge tone="amber">{t('compare.climateEstimate')}</Badge>}
          <div className="text-xs text-slate-500">{t('compare.daysPoor', { poor: w.poor_days, total: w.total_days })}</div>
        </>
      )
    },
  },
  {
    key: 'visa',
    render: (s, t) => {
      const v = s.visa
      if (!v) return null
      const fee = num(v.fee_usd) ? (v.fee_usd === 0 ? t('compare.noFee') : t('compare.fee', { amount: fmtUsd(v.fee_usd) })) : null
      const stay = num(v.max_stay_days) ? t('compare.maxStay', { count: v.max_stay_days }) : null
      return (
        <>
          <span className="font-semibold">{v.visa_type || DASH}</span>
          {v.verified ? <Badge tone="emerald">{t('compare.verified')}</Badge> : <Badge tone="amber">{t('compare.aiCheck')}</Badge>}
          <div className="text-xs text-slate-500">{[fee, stay].filter(Boolean).join(' · ')}</div>
        </>
      )
    },
  },
  {
    key: 'ease',
    render: (s, t) => {
      if (!num(s.ease?.total)) return null
      const g = GRADES[s.ease.grade]
      return (
        <>
          <span className="font-semibold">{Math.round(s.ease.total)}/100</span>
          {g && <span className={`ml-1.5 inline-block text-[10px] font-bold px-1.5 py-0.5 rounded-full border ${g.cls}`}>{t(`compare.grade.${s.ease.grade}`)}</span>}
        </>
      )
    },
  },
  { key: 'safety', render: (s) => (num(s.ease?.safety) ? `${s.ease.safety}/20` : null) },
  { key: 'english', render: (s) => (num(s.ease?.english) ? `${s.ease.english}/20` : null) },
  { key: 'daily', render: (s, t) => (num(s.daily_cost_usd) ? t('compare.perDay', { amount: fmtUsd(s.daily_cost_usd) }) : null) },
]

function Skeleton() {
  return (
    <div data-testid="compare-skeleton" className="animate-pulse space-y-1.5">
      <div className="h-4 w-20 bg-slate-200 rounded" />
    </div>
  )
}

function Cell({ col, row, best }) {
  const { t } = useTranslation('misc')
  if (col.status === 'loading') return <Skeleton />
  if (col.status === 'error' || !col.summary) return <span className="text-slate-300">{DASH}</span>
  const content = row.render(col.summary, t)
  if (!content) return <span className="text-slate-400">{DASH}</span>
  return <>{content}{best && <Best t={t} />}</>
}

function PlanButton({ index, col, onPlan }) {
  const { t } = useTranslation('misc')
  if (col.status !== 'done') return null
  return (
    <button
      type="button"
      data-tid="compare.plan"
      onClick={() => { track('compare_plan_clicked', 'search', { position: index }); onPlan(index) }}
      className="w-full px-3 py-1.5 text-xs font-semibold rounded-lg bg-teal-600 text-white hover:bg-teal-700"
    >
      {t('compare.planThis')}
    </button>
  )
}

function Header({ col, index, onRetry }) {
  const { t } = useTranslation('misc')
  const title = col.summary?.label || col.destination
  return (
    <div>
      <div className="font-bold text-slate-800">{title}</div>
      {col.status === 'error' && (
        <div className="mt-1 text-xs text-red-600">
          {t('compare.couldntLoad')}{' '}
          <button type="button" onClick={() => onRetry(index)} data-tid="compare.retry" className="underline font-semibold">{t('compare.retry')}</button>
          {typeof col.error === 'string' && col.error && <div className="text-slate-500 font-normal">{col.error}</div>}
        </div>
      )}
      {col.status === 'done' && col.summary?.missing?.length > 0 && (
        <div className="mt-1 text-xs text-amber-600">{t('compare.missing', { list: col.summary.missing.join(', ') })}</div>
      )}
    </div>
  )
}

export default function CompareTable({ columns, onPlan, onRetry }) {
  const { t } = useTranslation('misc')
  const best = bestByRow(columns.map((c) => (c.status === 'done' ? c.summary : null)))
  const isBest = (row, i) => best[row.key]?.has(i)

  return (
    <div>
      {/* ≥ md: table */}
      <div className="hidden md:block overflow-x-auto">
        <table className="w-full text-sm text-left border-collapse">
          <thead>
            <tr>
              <th className="p-3 w-44" />
              {columns.map((c, i) => (
                <th key={i} className="p-3 align-top"><Header col={c} index={i} onRetry={onRetry} /></th>
              ))}
            </tr>
          </thead>
          <tbody>
            {ROWS.map((row) => (
              <tr key={row.key} className="border-t border-slate-100">
                <th scope="row" className="p-3 text-xs font-semibold text-slate-500 align-top">{t(`compare.row.${row.key}`)}</th>
                {columns.map((c, i) => (
                  <td key={i} className="p-3 align-top"><Cell col={c} row={row} best={isBest(row, i)} /></td>
                ))}
              </tr>
            ))}
            <tr className="border-t border-slate-100">
              <td />
              {columns.map((c, i) => <td key={i} className="p-3"><PlanButton index={i} col={c} onPlan={onPlan} /></td>)}
            </tr>
          </tbody>
        </table>
      </div>

      {/* < md: stacked cards */}
      <div className="md:hidden space-y-3">
        {columns.map((c, i) => (
          <div key={i} className="rounded-xl border border-slate-200 bg-white p-4 space-y-2">
            <Header col={c} index={i} onRetry={onRetry} />
            {ROWS.map((row) => (
              <div key={row.key} className="flex justify-between gap-3 text-sm border-t border-slate-50 pt-1.5">
                <span className="text-xs font-semibold text-slate-500 shrink-0">{t(`compare.row.${row.key}`)}</span>
                <span className="text-right min-w-0"><Cell col={c} row={row} best={isBest(row, i)} /></span>
              </div>
            ))}
            <PlanButton index={i} col={c} onPlan={onPlan} />
          </div>
        ))}
      </div>
    </div>
  )
}
