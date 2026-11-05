import { matchedElsewhere } from '../../../utils/hotelWatch'
import { isUnavailable } from '../../../utils/priceWatch'
import PriceWatchCard from './PriceWatchCard'

const nightsOf = (s) => (s?.check_in && s?.check_out
  ? Math.round((Date.parse(s.check_out) - Date.parse(s.check_in)) / 86400000)
  : null)

// Said only when the live look told us which price it was
const TAXES = { true: ', taxes and fees included.', false: ', before taxes and fees.' }

function HotelDetails({ watch }) {
  const s = watch.subject || {}
  const taxes = watch.last_observation?.observed?.taxes_included
  const nights = nightsOf(s)
  const past = watch.status === 'expired'
  return (
    <div className="mt-2 space-y-1 text-xs text-slate-500">
      {nights != null && (
        <p>Total for {nights} night{nights === 1 ? '' : 's'}{s.city ? ` in ${String(s.city).split(',')[0]}` : ''} on Google Hotels{TAXES[taxes] ?? '.'}</p>
      )}
      {matchedElsewhere(watch) && <p>Your plan called it “{s.requested_name}”.</p>}
      {!past && isUnavailable(watch) && (
        <p className="inline-flex rounded-full border border-slate-200 bg-slate-100 px-2 py-0.5 font-medium text-slate-700">Sold out for your dates</p>
      )}
    </div>
  )
}

/** A watched hotel on the Alerts page: property, stay, total + nightly, sold-out state, Book link. */
export default function HotelWatchCard(props) {
  return (
    <PriceWatchCard {...props} Details={HotelDetails} openLabel="Book" unitLabel="a night"
      unavailableText="No rooms for your dates right now. We’ll keep checking and won’t alert you until it’s back." />
  )
}
