import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../../context/AuthContext'
import { getQuota } from '../../services/accountApi'
import { fmtDate, fmtNumber } from '../../i18n/format'

const BUCKETS = ['search', 'chat', 'compare', 'discover', 'light_ai', 'import']

// Daily AI allowance per bucket. Hidden when signed out, before the account
// loads, or when the backend has no quota endpoint (404 / any failure).
export default function QuotaSection({ account }) {
  const { t } = useTranslation('quota')
  const { token } = useAuth()
  const [quota, setQuota] = useState(null)

  useEffect(() => {
    if (!account || !token) return undefined
    let live = true
    getQuota(token).then((q) => { if (live) setQuota(q) }).catch(() => { if (live) setQuota(null) })
    return () => { live = false }
  }, [account, token])

  if (!account || !quota?.buckets) return null
  const resets = fmtDate(quota.resets_at, { hour: 'numeric', minute: '2-digit' })

  return (
    <section data-tid="quota.section" className="bg-white rounded-2xl shadow p-5 mb-4">
      <h2 className="text-lg font-semibold text-slate-800">{t('title')}</h2>
      <p className="text-sm text-slate-500 mb-3">{t('intro')}</p>
      <ul className="space-y-3">
        {BUCKETS.filter((b) => quota.buckets[b]).map((b) => {
          const { used = 0, limit } = quota.buckets[b]
          const unlimited = limit == null
          const pct = unlimited || limit <= 0 ? 0 : Math.min(100, Math.round((used / limit) * 100))
          return (
            <li key={b} data-tid={`quota.bucket.${b}`}>
              <div className="flex justify-between text-sm text-slate-700">
                <span>{t(`buckets.${b}`)}</span>
                <span data-tid={`quota.count.${b}`}>
                  {unlimited ? t('unlimited') : t('usedOf', { used: fmtNumber(used), limit: fmtNumber(limit) })}
                </span>
              </div>
              {!unlimited && (
                <div
                  role="progressbar" aria-valuemin={0} aria-valuemax={limit} aria-valuenow={Math.min(used, limit)}
                  aria-label={t(`buckets.${b}`)}
                  className="h-2 mt-1 rounded-full bg-slate-200 overflow-hidden"
                >
                  <div
                    className={`h-full ${pct >= 100 ? 'bg-red-500' : 'bg-teal-500'}`}
                    style={{ width: `${pct}%` }}
                  />
                </div>
              )}
            </li>
          )
        })}
      </ul>
      {resets && <p data-tid="quota.resets" className="text-xs text-slate-500 mt-3">{t('resetsAt', { time: resets })}</p>}
    </section>
  )
}
