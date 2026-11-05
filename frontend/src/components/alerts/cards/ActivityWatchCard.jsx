import { Star } from 'lucide-react'
import { isUnavailable } from '../../../utils/priceWatch'
import {
  formatPrice, perPerson, providerName, titleDiffers, watchCurrency,
} from '../../../utils/activityWatch'
import PriceWatchCard from './PriceWatchCard'

const people = (n) => (n === 1 ? '1 traveller' : `${n} travellers`)

function ActivityDetails({ watch }) {
  const subject = watch.subject || {}
  const obs = watch.last_observation || {}
  const observed = obs.observed || {}
  const currency = watchCurrency(watch)
  const provider = providerName(subject.provider || observed.provider)
  const n = subject.travellers || 1
  const unit = perPerson(watch)
  const total = watch.last_price ?? watch.baseline_price
  const money = (v) => formatPrice(v, currency)
  const rating = observed.rating ?? null
  return (
    <div className="mt-3 space-y-1 text-sm text-slate-600">
      <p className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-slate-500">
        <span className="font-semibold uppercase tracking-wide">{provider}</span>
        {rating != null && (
          <span className="inline-flex items-center gap-0.5">
            <Star size={11} className="fill-amber-400 text-amber-400" aria-hidden="true" />{rating}
            {observed.reviews ? ` (${observed.reviews.toLocaleString('en-US')})` : ''}
          </span>
        )}
        {titleDiffers(subject.name, watch.title) && <span>for “{subject.name}”</span>}
      </p>
      {!isUnavailable(watch) && unit != null && (
        <p className="tabular-nums">
          from <strong className="text-slate-800">{money(unit)}</strong> per person
          {n > 1 && total != null && <> × {people(n)} = <strong className="text-slate-800">{money(total)}</strong></>}
        </p>
      )}
      {isUnavailable(watch) && observed.reason === 'currency_changed' && (
        <p className="text-xs text-slate-500">
          The listing now shows prices in {observed.seen_currency}; we only compare {currency} with {currency}.
        </p>
      )}
      <p className="text-[11px] text-slate-400">Price as shown in Google results for {provider}.</p>
    </div>
  )
}

/** An activity price watch on the Alerts page (see ./PriceWatchCard). */
export default function ActivityWatchCard(props) {
  return (
    <PriceWatchCard {...props} Details={ActivityDetails} openLabel="Open listing" unitLabel="per person"
      unavailableText="Not currently listed with a price in Google results. We’ll keep looking and won’t alert you until it’s back." />
  )
}
