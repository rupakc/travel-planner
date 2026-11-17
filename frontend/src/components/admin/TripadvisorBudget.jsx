import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { getTripadvisorBudget } from '../../services/api'
import { fmtNumber } from '../../i18n/format'

/**
 * Admin: Tripadvisor billable entities used against the hard cap. Probes
 * GET /api/admin/tripadvisor/budget once; any failure (404 on an older
 * backend) hides the panel.
 */
export default function TripadvisorBudget({ token }) {
  const { t } = useTranslation('adminTelemetry')
  const [budget, setBudget] = useState(null)

  useEffect(() => {
    let live = true
    getTripadvisorBudget(token)
      .then((b) => live && setBudget(b && typeof b === 'object' ? b : null))
      .catch(() => live && setBudget(null))
    return () => { live = false }
  }, [token])

  if (!budget) return null
  const used = Number(budget.used) || 0
  const cap = Number(budget.cap) || 0
  const pct = cap > 0 ? Math.min(100, Math.round((used / cap) * 100)) : 0
  const warn = cap > 0 && used >= (Number(budget.warn_at) || cap)
  return (
    <section data-testid="tripadvisor-budget" className="mt-6 rounded-xl border border-gray-200 bg-white p-4">
      <h2 className="text-sm font-semibold text-gray-800">{t('tripadvisor.title')}</h2>
      {!budget.enabled && <p className="mt-1 text-xs text-gray-500">{t('tripadvisor.off')}</p>}
      <p className="mt-2 text-sm text-gray-700">
        {t('tripadvisor.used', { used: fmtNumber(used), cap: fmtNumber(cap) })}
      </p>
      <div className="mt-2 h-2 w-full rounded-full bg-gray-100" role="progressbar"
        aria-valuemin={0} aria-valuemax={cap} aria-valuenow={used}>
        <div className={`h-2 rounded-full ${budget.paused ? 'bg-red-500' : warn ? 'bg-amber-500' : 'bg-teal-600'}`}
          style={{ width: `${pct}%` }} />
      </div>
      {budget.paused
        ? <p className="mt-2 text-xs text-red-600">{t('tripadvisor.paused')}</p>
        : warn && <p className="mt-2 text-xs text-amber-700">{t('tripadvisor.warn')}</p>}
    </section>
  )
}
