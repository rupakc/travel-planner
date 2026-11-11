import { useRef } from 'react'
import { useTranslation } from 'react-i18next'

// A 1..5 star radio group. Arrow keys move and select (Left/Down lower,
// Right/Up raise, Home/End jump); clicking the chosen star clears it (null).
export default function RatingStars({ value = null, onChange, name = 'rating', disabled = false }) {
  const { t } = useTranslation('journal')
  const refs = useRef([])
  const current = Number.isInteger(value) && value >= 1 && value <= 5 ? value : null

  const choose = (n, focus = true) => {
    onChange?.(n)
    if (focus && n) refs.current[n - 1]?.focus()
  }

  const onKeyDown = (e) => {
    if (disabled) return
    const from = current || 0
    let next = null
    if (e.key === 'ArrowRight' || e.key === 'ArrowUp') next = Math.min(5, from + 1)
    else if (e.key === 'ArrowLeft' || e.key === 'ArrowDown') next = Math.max(1, from - 1)
    else if (e.key === 'Home') next = 1
    else if (e.key === 'End') next = 5
    if (next === null) return
    e.preventDefault()
    choose(next)
  }

  return (
    <div role="radiogroup" aria-label={t('stars.group')} className="inline-flex" data-tid={`${name}-stars`}>
      {[1, 2, 3, 4, 5].map((n) => {
        const checked = current === n
        return (
          <button
            key={n}
            ref={(el) => { refs.current[n - 1] = el }}
            type="button"
            role="radio"
            aria-checked={checked}
            aria-label={t('stars.label', { n })}
            tabIndex={checked || (!current && n === 1) ? 0 : -1}
            disabled={disabled}
            onKeyDown={onKeyDown}
            onClick={() => choose(checked ? null : n, false)}
            data-tid={`${name}-star-${n}`}
            className="flex h-11 w-9 items-center justify-center text-2xl leading-none sm:h-9 sm:w-8"
          >
            <span aria-hidden="true" className={current && n <= current ? 'text-amber-500' : 'text-slate-300 dark:text-slate-600'}>
              {current && n <= current ? '★' : '☆'}
            </span>
          </button>
        )
      })}
    </div>
  )
}
