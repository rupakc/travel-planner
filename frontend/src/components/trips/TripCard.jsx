import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { fmtDate } from '../../i18n/format'
import { tripPath } from '../../journey/paths'

const fmt = (iso) => fmtDate(iso, { dateStyle: 'medium', timeZone: 'UTC' })

export function tripDates(trip) {
  if (!trip.start_date) return ''
  const start = fmt(trip.start_date)
  return trip.end_date && trip.end_date !== trip.start_date ? `${start} – ${fmt(trip.end_date)}` : start
}

export default function TripCard({ trip }) {
  const { t } = useTranslation('trips')
  const dates = tripDates(trip)
  return (
    <Link
      to={tripPath(trip.id)}
      data-tid={`trips-card-${trip.id}`}
      className="block min-h-[44px] rounded-xl border border-slate-200 bg-white p-4 shadow-sm hover:border-teal-600"
    >
      <div className="font-semibold text-slate-900">{trip.title}</div>
      {trip.destination && <div className="text-sm text-slate-600">{trip.destination}</div>}
      <div className="mt-1 text-xs text-slate-500">{dates || t('card.noDates')}</div>
    </Link>
  )
}
