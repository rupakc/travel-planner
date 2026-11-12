import { useEffect, useId, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { countAtOrBelow } from '../../utils/alertStory'
import { fmtCurrency } from '../../i18n/format'

/**
 * Target price slider. Dragging only previews how many of the recent checks
 * were at or below the value; `onCommit(value)` fires once, on release.
 */
export default function TargetSlider({ min, max, value, points = [], step = 1, onCommit, currency = 'USD' }) {
  const { t } = useTranslation('priceStory')
  const id = useId()
  const [v, setV] = useState(value ?? max)
  const committed = useRef(value ?? max)
  const latest = useRef(v)
  useEffect(() => { if (value != null) { setV(value); latest.current = value; committed.current = value } }, [value])

  const move = (e) => { const n = Number(e.target.value); latest.current = n; setV(n) }
  const timer = useRef(null)
  const release = () => {
    clearTimeout(timer.current)
    if (latest.current === committed.current) return
    committed.current = latest.current
    onCommit?.(latest.current)
  }
  // Arrow keys commit after a short pause, not on every keystroke.
  const keyRelease = () => { clearTimeout(timer.current); timer.current = setTimeout(release, 600) }
  useEffect(() => () => clearTimeout(timer.current), [])
  const total = points.length
  const count = countAtOrBelow(points, v)

  return (
    <div className="space-y-1">
      <label htmlFor={id} className="flex items-baseline justify-between text-sm font-medium text-slate-700">
        <span>{t('slider.label')}</span>
        <span className="tabular-nums">{fmtCurrency(v, currency)}</span>
      </label>
      <input
        id={id} type="range" min={min} max={max} step={step} value={v}
        onChange={move} onPointerUp={release} onTouchEnd={release} onKeyUp={keyRelease} onBlur={release}
        data-tid="price-story-target-slider"
        className="w-full min-h-[44px] accent-sky-600"
      />
      {total > 0 && (
        <p className="text-xs text-slate-500" aria-live="polite">
          {count > 0 ? t('slider.preview', { count, total }) : t('slider.none', { total })}
        </p>
      )}
    </div>
  )
}
