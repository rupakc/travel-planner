import { useRef } from 'react'
import { useTranslation } from 'react-i18next'

// The trip screen's tab strip (from journey/tripTabs.resolveTabs). A disabled
// tab (offline) stays visible but can't be opened. Left/Right move between
// the enabled tabs. The panel is `trip-panel-<tab>`.
export default function TripTabs({ tabs, enabled, active, onSelect }) {
  const { t } = useTranslation(['trip', 'journey'])
  const ref = useRef(null)

  const onKey = (e) => {
    if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return
    const usable = tabs.filter((tab) => enabled.includes(tab))
    const at = usable.indexOf(active)
    if (at < 0 || usable.length < 2) return
    e.preventDefault()
    const next = usable[(at + (e.key === 'ArrowRight' ? 1 : -1) + usable.length) % usable.length]
    onSelect(next)
    ref.current?.querySelector(`[data-tid="trip.tab.${next}"]`)?.focus()
  }

  return (
    <div
      ref={ref}
      role="tablist"
      aria-label={t('tabsLabel')}
      data-tid="trip.tabs"
      onKeyDown={onKey}
      className="-mx-4 flex gap-1 overflow-x-auto px-4 [scrollbar-width:none] sm:mx-0 sm:px-0"
    >
      {tabs.map((tab) => {
        const selected = tab === active
        const off = !enabled.includes(tab)
        return (
          <button
            key={tab}
            type="button"
            role="tab"
            id={`trip-tab-${tab}`}
            aria-selected={selected}
            aria-controls={`trip-panel-${tab}`}
            tabIndex={selected ? 0 : -1}
            disabled={off}
            data-tid={`trip.tab.${tab}`}
            onClick={() => onSelect(tab)}
            className={`min-h-[44px] shrink-0 whitespace-nowrap rounded-full px-4 text-sm font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-600 ${
              selected
                ? 'bg-teal-700 text-white'
                : 'bg-white/70 text-gray-700 hover:bg-white disabled:cursor-not-allowed disabled:bg-transparent disabled:text-gray-400'
            }`}
          >
            {t(`journey:tripTabs.${tab}`)}
          </button>
        )
      })}
    </div>
  )
}
