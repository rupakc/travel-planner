import { bestByRow, fmtUsd, fmtDuration } from '../utils/compare'
import { track } from '../utils/analytics'

const DASH = '—'

// Backend Travel Ease grade (static_results.get_confidence_score) -> chip
const GRADES = {
  green: { label: 'Easy', cls: 'bg-emerald-50 text-emerald-700 border-emerald-200' },
  amber: { label: 'Moderate', cls: 'bg-amber-50 text-amber-700 border-amber-200' },
  red: { label: 'Hard', cls: 'bg-red-50 text-red-700 border-red-200' },
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

const Best = () => <Badge tone="emerald">Best</Badge>

const num = (v) => typeof v === 'number' && Number.isFinite(v)
const temp = (v) => (num(v) ? `${Math.round(v)}°` : DASH)

// Each row: key (matches bestByRow where numeric), label, render(summary) -> node | null
const ROWS = [
  {
    key: 'estimate', label: 'Est. trip cost / person',
    render: (s) => {
      const e = s.estimate
      if (!e || !num(e.total_usd)) return null
      return (
        <>
          <span className="font-semibold">{fmtUsd(e.total_usd)}</span>
          <Badge>estimate</Badge>
          {e.budget_status === 'under' && <Badge tone="emerald">Under budget</Badge>}
          {e.budget_status === 'over' && <Badge tone="red">Over budget</Badge>}
          {e.partial && <div className="text-xs text-slate-500 mt-0.5">partial — some costs unknown</div>}
        </>
      )
    },
  },
  {
    key: 'flight', label: 'Cheapest flight / person',
    render: (s) => {
      const f = s.flight
      if (!f) return null
      const stops = !num(f.stops) ? null : f.stops === 0 ? 'Nonstop' : `${f.stops} stop${f.stops > 1 ? 's' : ''}`
      const dur = fmtDuration(f.duration_minutes)
      return (
        <>
          <span className="font-semibold">{fmtUsd(f.price_usd)}</span>
          {f.source === 'estimate' && <Badge tone="amber">estimate</Badge>}
          <div className="text-xs text-slate-500">{[stops, dur, f.airline].filter(Boolean).join(' · ')}</div>
        </>
      )
    },
  },
  {
    key: 'hotel', label: 'Hotel / night',
    render: (s) => {
      const h = s.hotel
      if (!h) return null
      return (
        <>
          <span className="font-semibold">{fmtUsd(h.typical_nightly_usd)}</span> typical
          {num(h.cheapest_good_nightly_usd) && <div className="text-xs text-slate-500">from {fmtUsd(h.cheapest_good_nightly_usd)} (well reviewed)</div>}
        </>
      )
    },
  },
  {
    key: 'weather', label: 'Weather',
    render: (s) => {
      const w = s.weather
      if (!w) return null
      return (
        <>
          <span className="font-semibold">{temp(w.avg_high_c)} / {temp(w.avg_low_c)}{num(w.avg_high_c) || num(w.avg_low_c) ? 'C' : ''}</span>
          {w.source !== 'open-meteo' && <Badge tone="amber">climate estimate</Badge>}
          <div className="text-xs text-slate-500">{w.poor_days} of {w.total_days} days poor</div>
        </>
      )
    },
  },
  {
    key: 'visa', label: 'Visa',
    render: (s) => {
      const v = s.visa
      if (!v) return null
      const fee = num(v.fee_usd) ? (v.fee_usd === 0 ? 'no fee' : `${fmtUsd(v.fee_usd)} fee`) : null
      const stay = num(v.max_stay_days) ? `${v.max_stay_days} days max` : null
      return (
        <>
          <span className="font-semibold">{v.visa_type || DASH}</span>
          {v.verified ? <Badge tone="emerald">Verified</Badge> : <Badge tone="amber">AI — check official site</Badge>}
          <div className="text-xs text-slate-500">{[fee, stay].filter(Boolean).join(' · ')}</div>
        </>
      )
    },
  },
  {
    key: 'ease', label: 'Travel Ease',
    render: (s) => {
      if (!num(s.ease?.total)) return null
      const g = GRADES[s.ease.grade]
      return (
        <>
          <span className="font-semibold">{Math.round(s.ease.total)}/100</span>
          {g && <span className={`ml-1.5 inline-block text-[10px] font-bold px-1.5 py-0.5 rounded-full border ${g.cls}`}>{g.label}</span>}
        </>
      )
    },
  },
  { key: 'safety', label: 'Safety', render: (s) => (num(s.ease?.safety) ? `${s.ease.safety}/20` : null) },
  { key: 'english', label: 'English', render: (s) => (num(s.ease?.english) ? `${s.ease.english}/20` : null) },
  { key: 'daily', label: 'Typical daily spend / person', render: (s) => (num(s.daily_cost_usd) ? `${fmtUsd(s.daily_cost_usd)} / day` : null) },
]

function Skeleton() {
  return (
    <div data-testid="compare-skeleton" className="animate-pulse space-y-1.5">
      <div className="h-4 w-20 bg-slate-200 rounded" />
    </div>
  )
}

function Cell({ col, row, best }) {
  if (col.status === 'loading') return <Skeleton />
  if (col.status === 'error' || !col.summary) return <span className="text-slate-300">{DASH}</span>
  const content = row.render(col.summary)
  if (!content) return <span className="text-slate-400">{DASH}</span>
  return <>{content}{best && <Best />}</>
}

function PlanButton({ index, col, onPlan }) {
  if (col.status !== 'done') return null
  return (
    <button
      type="button"
      onClick={() => { track('compare_plan_clicked', 'search', { position: index }); onPlan(index) }}
      className="w-full px-3 py-1.5 text-xs font-semibold rounded-lg bg-teal-600 text-white hover:bg-teal-700"
    >
      Plan this trip
    </button>
  )
}

function Header({ col, index, onRetry }) {
  const title = col.summary?.label || col.destination
  return (
    <div>
      <div className="font-bold text-slate-800">{title}</div>
      {col.status === 'error' && (
        <div className="mt-1 text-xs text-red-600">
          Couldn&apos;t load{' '}
          <button type="button" onClick={() => onRetry(index)} className="underline font-semibold">Retry</button>
          {typeof col.error === 'string' && col.error && <div className="text-slate-500 font-normal">{col.error}</div>}
        </div>
      )}
      {col.status === 'done' && col.summary?.missing?.length > 0 && (
        <div className="mt-1 text-xs text-amber-600">Missing: {col.summary.missing.join(', ')}</div>
      )}
    </div>
  )
}

export default function CompareTable({ columns, onPlan, onRetry }) {
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
                <th scope="row" className="p-3 text-xs font-semibold text-slate-500 align-top">{row.label}</th>
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
                <span className="text-xs font-semibold text-slate-500 shrink-0">{row.label}</span>
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
