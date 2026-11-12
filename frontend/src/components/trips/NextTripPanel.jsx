import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { fmtDate } from '../../i18n/format'
import { tripPath } from '../../journey/paths'

const primary = 'inline-flex min-h-[44px] items-center rounded-lg bg-teal-700 px-4 py-2 text-sm font-medium text-white hover:bg-teal-800'
const secondary = 'inline-flex min-h-[44px] items-center rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-800 hover:bg-slate-50'

// The pinned trip with one "what now" line for its phase. `prep` is the
// getPrep answer for a Ready trip (null while loading or when it failed).
export default function NextTripPanel({ trip, prep }) {
  const { t } = useTranslation('trips')
  const id = trip.id
  let line = null
  let actions = null

  if (trip.phase === 'dreaming') {
    line = t('next.dreaming')
    actions = (
      <>
        <Link to={tripPath(id, 'overview')} data-tid="trips-next-pick-dates" className={primary}>{t('next.pickDates')}</Link>
        <Link to="/explore" state={trip.destination ? { prefill: { destination: trip.destination } } : undefined} data-tid="trips-next-plan-it" className={secondary}>{t('next.planIt')}</Link>
      </>
    )
  } else if (trip.phase === 'planning') {
    line = t('next.planning', { percent: trip.prep?.percent ?? 0 })
    actions = <Link to={tripPath(id, 'overview')} data-tid="trips-next-open" className={primary}>{t('next.open')}</Link>
  } else if (trip.phase === 'ready') {
    const item = prep?.items?.find((i) => i.status === 'todo')
    if (item) {
      const name = t(`prepItems.${item.id}`, { defaultValue: item.id })
      line = item.due
        ? t('next.ready', { item: name, date: fmtDate(item.due, { dateStyle: 'medium', timeZone: 'UTC' }) })
        : t('next.readyNoDate', { item: name })
    } else {
      line = prep ? t('next.allSet') : t('next.readyFallback')
    }
    actions = <Link to={tripPath(id, 'prep')} data-tid="trips-next-open-prep" className={primary}>{t('next.openPrep')}</Link>
  } else if (trip.phase === 'on_the_road') {
    line = t('next.onTheRoad', { day: trip.day_index ?? 1, city: trip.destination || trip.destinations?.[0] || trip.title })
    actions = <Link to={tripPath(id, 'today')} data-tid="trips-next-open-today" className={primary}>{t('next.openToday')}</Link>
  } else {
    line = t('next.memories')
    actions = <Link to={tripPath(id, 'recap')} data-tid="trips-next-open-recap" className={primary}>{t('next.openRecap')}</Link>
  }

  return (
    <section
      data-tid="trips-next-panel"
      aria-label={t('next.heading')}
      className="rounded-2xl border border-teal-200 bg-teal-50 p-4"
    >
      <div className="text-xs font-semibold uppercase tracking-wide text-teal-800">{t('next.heading')}</div>
      <div className="mt-1 text-lg font-semibold text-slate-900">{trip.title}</div>
      <div data-tid="trips-next-line" className="mt-1 text-sm text-slate-700">{line}</div>
      <div className="mt-3 flex flex-wrap gap-2">{actions}</div>
    </section>
  )
}
