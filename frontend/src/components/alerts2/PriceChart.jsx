import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { fmtCurrency, fmtDate } from '../../i18n/format'

const W = 320
const H = 140
const PAD = { l: 8, r: 8, t: 12, b: 12 }

export const prefersReducedMotion = () => {
  try { return !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches } catch { return false }
}

/**
 * SVG price line: typical band, lowest marker, target line, baseline dot.
 * Hover/tap scrubs a tooltip; left/right arrows step between points and the
 * selected price and date are announced through an aria-live region.
 */
export default function PriceChart({ points, typical, target, baseline, lowest, currency }) {
  const { t } = useTranslation('priceStory')
  const [sel, setSel] = useState(null)
  const animate = useMemo(() => !prefersReducedMotion(), [])
  const [drawn, setDrawn] = useState(!animate)
  useEffect(() => { if (animate) { const r = requestAnimationFrame(() => setDrawn(true)); return () => cancelAnimationFrame(r) } }, [animate])

  const n = points.length
  const ys = points.map((p) => p.price)
  for (const v of [typical?.low, typical?.high, target, baseline]) if (typeof v === 'number') ys.push(v)
  const lo = Math.min(...ys)
  const hi = Math.max(...ys)
  const span = hi - lo || 1
  const x = (i) => PAD.l + (n === 1 ? 0 : (i * (W - PAD.l - PAD.r)) / (n - 1))
  const y = (v) => PAD.t + (1 - (v - lo) / span) * (H - PAD.t - PAD.b)
  const path = points.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)} ${y(p.price).toFixed(1)}`).join(' ')
  const money = (v) => fmtCurrency(v, currency)
  const day = (at) => fmtDate(at, { month: 'short', day: 'numeric' })
  const lowIdx = lowest == null ? -1 : points.findIndex((p) => p.price === lowest)

  const pick = (e) => {
    const r = e.currentTarget.getBoundingClientRect()
    if (!r.width) return
    const frac = (e.clientX - r.left) / r.width
    setSel(Math.max(0, Math.min(n - 1, Math.round(frac * (n - 1)))))
  }
  const onKey = (e) => {
    if (e.key === 'ArrowLeft') { e.preventDefault(); setSel((s) => Math.max(0, (s ?? n) - 1)) }
    else if (e.key === 'ArrowRight') { e.preventDefault(); setSel((s) => Math.min(n - 1, (s ?? -1) + 1)) }
    else if (e.key === 'Escape') setSel(null)
  }
  const cur = sel != null ? points[sel] : null
  const label = t('chart.label', { n, from: day(points[0].at), to: day(points[n - 1].at) })

  return (
    <div className="relative">
      <div
        role="group" tabIndex={0} aria-label={`${label}. ${t('chart.help')}`}
        onKeyDown={onKey} onPointerMove={pick} onPointerDown={pick} onPointerLeave={() => setSel(null)}
        onBlur={() => setSel(null)}
        className="rounded-lg touch-pan-y focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-500"
      >
        <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto" aria-hidden="true" data-testid="price-chart">
          {typical && (
            <rect data-testid="typical-band" x={PAD.l} width={W - PAD.l - PAD.r} y={y(typical.high)}
              height={Math.max(1, y(typical.low) - y(typical.high))} className="fill-sky-100 dark:fill-sky-900/40" />
          )}
          {typeof target === 'number' && (
            <line data-testid="target-line" x1={PAD.l} x2={W - PAD.r} y1={y(target)} y2={y(target)}
              strokeDasharray="4 3" className="stroke-emerald-600" strokeWidth="1.5" />
          )}
          <path d={path} fill="none" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round"
            className="stroke-sky-600 dark:stroke-sky-400" pathLength="1"
            {...(animate ? { 'data-draw': 'in', style: { strokeDasharray: 1, strokeDashoffset: drawn ? 0 : 1, transition: 'stroke-dashoffset .8s ease' } } : {})} />
          {typeof baseline === 'number' && (
            <circle data-testid="baseline-dot" cx={x(0)} cy={y(baseline)} r="3.5" fill="none" strokeWidth="1.5" className="stroke-slate-500" />
          )}
          {lowIdx >= 0 && (
            <path data-testid="lowest-marker" transform={`translate(${x(lowIdx)} ${y(lowest)})`} d="M0 -6 L5 3 L-5 3 Z" className="fill-emerald-600" />
          )}
          {cur && (
            <g>
              <line x1={x(sel)} x2={x(sel)} y1={PAD.t} y2={H - PAD.b} className="stroke-slate-400" strokeWidth="1" />
              <circle cx={x(sel)} cy={y(cur.price)} r="4" className="fill-sky-600" />
            </g>
          )}
        </svg>
        {cur && (
          <div
            data-testid="chart-tooltip"
            className="pointer-events-none absolute top-0 -translate-x-1/2 rounded bg-slate-900 px-2 py-1 text-xs text-white shadow"
            style={{ left: `${(x(sel) / W) * 100}%` }}
          >
            {t('chart.point', { price: money(cur.price), date: day(cur.at) })}
          </div>
        )}
      </div>
      <p className="sr-only" aria-live="polite" data-testid="chart-live">
        {cur ? t('chart.point', { price: money(cur.price), date: day(cur.at) }) : ''}
      </p>
      <ul className="mt-1 flex flex-wrap gap-x-3 text-xs text-slate-500 dark:text-slate-400">
        {typical && <li>{t('chart.typical')}: {money(typical.low)}–{money(typical.high)}</li>}
        {lowest != null && <li>{t('chart.lowest', { price: money(lowest) })}</li>}
        {typeof target === 'number' && <li>{t('chart.target', { price: money(target) })}</li>}
        {typeof baseline === 'number' && <li>{t('chart.baseline', { price: money(baseline) })}</li>}
      </ul>
    </div>
  )
}
