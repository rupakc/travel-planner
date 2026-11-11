import { Info } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { fmtNumber } from '../i18n/format'
import { computePlanCostBreakdown } from '../utils/planHelpers'

// Literal class names so Tailwind keeps them; hues match the plan drawer cards
const COLORS = {
  flights: 'bg-sky-500',
  hotel: 'bg-purple-500',
  activities: 'bg-green-500',
  sim: 'bg-pink-500',
}

const usd = (n) => fmtNumber(n, { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })

const percentLabel = (share) => (share > 0 && share < 0.005 ? '<1%' : `${Math.round(share * 100)}%`)

/** Where the plan's money goes: a stacked bar plus one row per category. */
export default function CostBreakdown({ selections, searchData }) {
  const { t } = useTranslation('plan')
  const parts = computePlanCostBreakdown(selections, searchData)
  if (!parts.length) return null
  const label = (p) => t(`cost.cat.${p.key}`, { defaultValue: p.label })
  const total = parts.reduce((t, p) => t + p.amount, 0)
  const hasUnpricedTransport = (selections?.getting_around?.length || 0) > 0

  return (
    <section className="border border-gray-200 rounded-xl p-3" aria-labelledby="cost-breakdown-heading">
      <h3 id="cost-breakdown-heading" className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">{t('cost.heading')}</h3>

      <div className="flex h-2.5 rounded-full overflow-hidden bg-gray-100 gap-px" role="img"
        aria-label={parts.map(p => `${label(p)} ${percentLabel(p.amount / total)}`).join(', ')}>
        {parts.map(p => (
          <div key={p.key} className={COLORS[p.key]} style={{ width: `${(p.amount / total) * 100}%` }} />
        ))}
      </div>

      <ul className="mt-2.5 space-y-1">
        {parts.map((p, i) => (
          <li key={p.key} className="flex items-center gap-2 text-xs">
            <span className={`w-2 h-2 rounded-full shrink-0 ${COLORS[p.key]}`} aria-hidden="true" />
            <span className={`flex-1 ${i === 0 ? 'font-semibold text-gray-800' : 'text-gray-600'}`}>{label(p)}</span>
            <span className="tabular-nums text-gray-800 font-medium">{usd(p.amount)}</span>
            <span className="tabular-nums text-gray-400 w-9 text-right">{percentLabel(p.amount / total)}</span>
          </li>
        ))}
      </ul>

      {hasUnpricedTransport && (
        <p className="mt-2 flex items-start gap-1 text-[11px] text-gray-400">
          <Info size={10} className="mt-0.5 shrink-0" /> {t('cost.transportNote')}
        </p>
      )}
    </section>
  )
}
