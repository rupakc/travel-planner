import { useTranslation } from 'react-i18next'
import { matchedElsewhere } from '../../../utils/hotelWatch'
import { isUnavailable } from '../../../utils/priceWatch'
import PriceWatchCard from './PriceWatchCard'

const nightsOf = (s) => (s?.check_in && s?.check_out
  ? Math.round((Date.parse(s.check_out) - Date.parse(s.check_in)) / 86400000)
  : null)

// Said only when the live look told us which price it was
const taxesKey = (included) => (included === true ? 'hotel.taxesIn' : included === false ? 'hotel.taxesOut' : 'hotel.taxesUnknown')

function HotelDetails({ watch }) {
  const { t } = useTranslation('alerts')
  const s = watch.subject || {}
  const taxes = watch.last_observation?.observed?.taxes_included
  const nights = nightsOf(s)
  const past = watch.status === 'expired'
  return (
    <div className="mt-2 space-y-1 text-xs text-slate-500">
      {nights != null && (
        <p>
          {t('hotel.cardTotal', { count: nights, city: s.city ? String(s.city).split(',')[0] : '', context: s.city ? 'city' : undefined })}
          {t(taxesKey(taxes))}
        </p>
      )}
      {matchedElsewhere(watch) && <p>{t('hotel.planCalled', { requested: s.requested_name })}</p>}
      {!past && isUnavailable(watch) && (
        <p className="inline-flex rounded-full border border-slate-200 bg-slate-100 px-2 py-0.5 font-medium text-slate-700">{t('hotel.soldOut')}</p>
      )}
    </div>
  )
}

/** A watched hotel on the Alerts page: property, stay, total + nightly, sold-out state, Book link. */
export default function HotelWatchCard(props) {
  const { t } = useTranslation('alerts')
  return (
    <PriceWatchCard {...props} Details={HotelDetails} openLabel={t('hotel.book')} unitLabel={t('unit.night')}
      unavailableText={t('hotel.unavailable')} />
  )
}
