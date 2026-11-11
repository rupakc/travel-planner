import { useTranslation } from 'react-i18next'
import { Navigation as NavIcon } from 'lucide-react'
import { timeRange } from '../../utils/schedule'
import { directionsUrl, isApplePlatform } from '../../utils/mapsLinks'

/** The next stop of the day, with a Directions link. */
export default function NextUpCard({ slot, onDirections }) {
  const { t } = useTranslation('today')
  if (!slot) {
    return (
      <div data-tid="today-next-up" className="rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
        {t('nothingNext')}
      </div>
    )
  }
  const url = directionsUrl({ lat: slot.lat, lng: slot.lng, name: slot.activity }, { apple: isApplePlatform() })
  return (
    <div data-tid="today-next-up" className="rounded-xl border border-teal-200 bg-teal-50 p-4 dark:border-teal-800 dark:bg-teal-950">
      <p className="text-xs font-semibold uppercase tracking-wide text-teal-800 dark:text-teal-200">{t('nextUp')}</p>
      <p className="mt-1 text-base font-semibold text-slate-900 dark:text-slate-50">{slot.activity}</p>
      <p className="text-sm text-slate-600 dark:text-slate-300">{timeRange(slot)}</p>
      <a
        data-tid="today-next-directions"
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        onClick={() => onDirections?.()}
        className="mt-3 inline-flex min-h-[44px] items-center gap-2 rounded-lg bg-teal-700 px-4 text-sm font-medium text-white hover:bg-teal-800"
      >
        <NavIcon size={16} aria-hidden="true" />{t('directions')}
      </a>
    </div>
  )
}
