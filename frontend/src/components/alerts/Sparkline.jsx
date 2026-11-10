import { useId } from 'react'
import { useTranslation } from 'react-i18next'
import { formatUsd } from '../../utils/fareCalendar'
import { sparkGeometry } from '../../utils/fareWatch'

/**
 * Price history line with the target as a dashed line. The latest point is
 * marked; the whole graphic carries a text summary for screen readers
 * (`format` writes its prices; fares use whole US dollars).
 */
export default function Sparkline({ history, target = null, width = 280, height = 48, className = '', format = formatUsd }) {
  const { t } = useTranslation('alerts')
  const gradientId = useId()
  const g = sparkGeometry(history, { width, height, pad: 4, target })
  if (!g || g.points.length < 2) {
    return (
      <p className={`text-xs text-slate-400 ${className}`}>
        {g ? t('spark.later') : t('spark.none')}
      </p>
    )
  }
  const last = g.points[g.points.length - 1]
  const first = g.points[0]
  const down = last.price < first.price
  const stroke = down ? '#059669' : '#0284c7'
  const summary = t(target ? 'spark.summaryTarget' : 'spark.summary', {
    n: g.points.length, from: format(first.price), to: format(last.price),
    low: format(Math.min(...g.points.map(p => p.price))), target: target ? format(target) : '',
  })
  return (
    <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={summary}
      className={`block h-auto w-full overflow-visible ${className}`}>
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={stroke} stopOpacity="0.16" />
          <stop offset="100%" stopColor={stroke} stopOpacity="0" />
        </linearGradient>
      </defs>
      {g.targetY != null && (
        <line x1="0" x2={width} y1={g.targetY} y2={g.targetY} stroke="#94a3b8" strokeWidth="1"
          strokeDasharray="4 4" vectorEffect="non-scaling-stroke" data-testid="spark-target" />
      )}
      <path d={g.area} fill={`url(#${gradientId})`} />
      <path d={g.line} fill="none" stroke={stroke} strokeWidth="2" strokeLinejoin="round"
        strokeLinecap="round" vectorEffect="non-scaling-stroke" />
      <circle cx={last.x} cy={last.y} r="3.5" fill="#fff" stroke={stroke} strokeWidth="2" vectorEffect="non-scaling-stroke" />
    </svg>
  )
}
