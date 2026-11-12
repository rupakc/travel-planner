import { useTranslation } from 'react-i18next'

// Countries visited against the bucket-list goal, as a progress ring.
// Renders nothing without a goal (callers also hide it for hide_game).
export default function BucketRing({ count = 0, goal }) {
  const { t } = useTranslation('trips')
  if (!Number.isFinite(goal) || goal <= 0) return null
  const shown = Math.max(0, Math.min(count, goal))
  const radius = 20
  const circumference = 2 * Math.PI * radius
  const offset = circumference * (1 - shown / goal)
  return (
    <div
      data-tid="trips-bucket-ring"
      className="flex items-center gap-3 rounded-xl border border-slate-200 bg-white px-3 py-2 dark:border-slate-700 dark:bg-slate-800"
    >
      <svg width="52" height="52" viewBox="0 0 52 52" role="img" aria-label={t('bucket.label', { count, goal })}>
        <circle cx="26" cy="26" r={radius} fill="none" strokeWidth="6" className="stroke-slate-200 dark:stroke-slate-700" />
        <circle
          cx="26" cy="26" r={radius} fill="none" strokeWidth="6" strokeLinecap="round"
          strokeDasharray={circumference} strokeDashoffset={offset}
          transform="rotate(-90 26 26)" className="stroke-teal-700 dark:stroke-teal-400"
        />
      </svg>
      <div className="text-sm">
        <div className="font-semibold text-slate-900 dark:text-slate-100">{count} / {goal}</div>
        <div className="text-slate-600 dark:text-slate-300">{t('bucket.title')}</div>
      </div>
    </div>
  )
}
