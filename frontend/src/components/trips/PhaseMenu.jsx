import { useEffect, useLayoutEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { Check, CalendarClock } from 'lucide-react'

export const PHASES = ['dreaming', 'planning', 'ready', 'on_the_road', 'memories']

// The phase chip's menu: pick a stage by hand (an override), or go back to the
// stage the dates give ("Follow my dates", only while an override is set).
// Escape or a click outside closes it; focus starts on the current stage.
export default function PhaseMenu({ phase, manual, onPick, onFollow, onClose }) {
  const { t } = useTranslation(['trip', 'journey'])
  const ref = useRef(null)

  useEffect(() => {
    const menu = ref.current
    menu?.querySelector('[aria-checked="true"]')?.focus()
    const onDoc = (e) => {
      if (menu && !menu.contains(e.target) && !e.target.closest?.('[data-tid="trip.phase"]')) onClose()
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [onClose])

  // When the menu closes with focus inside it (Escape, a pick), focus goes back
  // to the chip. A layout-effect cleanup runs while the menu is still in the DOM.
  useLayoutEffect(() => {
    const menu = ref.current
    return () => {
      if (menu && menu.contains(document.activeElement)) {
        document.querySelector('[data-tid="trip.phase"]')?.focus()
      }
    }
  }, [])

  const onKey = (e) => {
    if (e.key === 'Escape') { e.preventDefault(); onClose(); return }
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return
    e.preventDefault()
    const items = [...ref.current.querySelectorAll('[role^="menuitem"]:not([disabled])')]
    const at = items.indexOf(document.activeElement)
    const next = e.key === 'ArrowDown' ? (at + 1) % items.length : (at - 1 + items.length) % items.length
    items[next]?.focus()
  }

  const item = 'flex w-full min-h-[44px] items-center gap-2 px-3 text-left text-sm rounded-lg focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-600'

  return (
    <div
      ref={ref}
      role="menu"
      aria-label={t('phaseMenu.title')}
      data-tid="trip.phaseMenu"
      onKeyDown={onKey}
      className="absolute left-0 top-full z-30 mt-2 w-64 max-w-[calc(100vw-2rem)] rounded-xl border border-gray-200 bg-white p-1.5 shadow-lg"
    >
      <p className="px-3 pb-1 pt-1.5 text-xs font-semibold uppercase tracking-wide text-gray-500">{t('phaseMenu.title')}</p>
      {PHASES.map((p) => {
        const current = p === phase
        return (
          <button
            key={p}
            type="button"
            role="menuitemradio"
            aria-checked={current}
            data-tid={`trip.phaseMenu.${p}`}
            onClick={() => onPick(p)}
            className={`${item} ${current ? 'font-semibold text-teal-800 bg-teal-50' : 'text-gray-700 hover:bg-gray-50'}`}
          >
            <span className="w-4 shrink-0">{current && <Check size={16} aria-hidden="true" />}</span>
            {t(`journey:phases.${p}`)}
          </button>
        )
      })}
      <div className="my-1 border-t border-gray-100" role="separator" />
      <button
        type="button"
        role="menuitem"
        disabled={!manual}
        data-tid="trip.phaseMenu.follow"
        onClick={onFollow}
        className={`${item} text-gray-700 hover:bg-gray-50 disabled:cursor-default disabled:opacity-50 disabled:hover:bg-transparent`}
      >
        <CalendarClock size={16} className="shrink-0" aria-hidden="true" />
        <span>
          <span className="block">{t('phaseMenu.follow')}</span>
          <span className="block text-xs text-gray-500">{t('phaseMenu.followHint')}</span>
        </span>
      </button>
    </div>
  )
}
