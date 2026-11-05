import { Link } from 'react-router-dom'
import { matchedElsewhere, money } from '../../../utils/hotelWatch'
import { priceWatchLink } from '../../../utils/priceWatch'

const nightsOf = (ci, co) => Math.round((Date.parse(co) - Date.parse(ci)) / 86400000)

/**
 * Hotel body of the price-watch dialog. Before: the AI price the page showed
 * (labelled as an estimate) and the stay we'll look up. After: the Google
 * Hotels property actually tracked, its live total and nightly rate, and a
 * note when Google lists it under another name than the card.
 */
export default function HotelDialogBody({ spec = {}, preview = {}, watch = null }) {
  if (watch) {
    const obs = watch.last_observation || {}
    const s = watch.subject || {}
    const total = watch.baseline_price ?? watch.last_price
    const nights = s.check_in && s.check_out ? nightsOf(s.check_in, s.check_out) : null
    return (
      <div className="text-sm text-slate-700">
        <p>Tracking: <strong className="text-slate-900">{watch.title}</strong> on Google Hotels</p>
        <p className="mt-1 text-xs text-slate-600 tabular-nums">
          {money(total, watch.currency)}{nights ? ` for ${nights} night${nights === 1 ? '' : 's'}` : ''}
          {obs.unit_price != null ? ` · ${money(obs.unit_price, watch.currency)} a night` : ''}
          {watch.subtitle ? ` · ${watch.subtitle}` : ''}
        </p>
        {matchedElsewhere(watch) && (
          <p className="mt-1.5 text-xs text-slate-600">
            Your plan calls it “{s.requested_name}”; Google Hotels lists it as “{watch.title}”.{' '}
            Not this one? <Link to={priceWatchLink(watch)} className="font-medium text-sky-700 underline underline-offset-2 hover:text-sky-900">Remove it on your Alerts page</Link>.
          </p>
        )}
      </div>
    )
  }
  return (
    <div className="mt-3 rounded-xl bg-slate-50 px-4 py-3">
      {preview.price != null && (
        <p className="text-sm text-slate-600">
          Shown now <span className="text-2xl font-semibold tabular-nums text-slate-900">{money(preview.price)}</span>
          <span className="ml-1.5 text-xs text-slate-500">{preview.priceLabel || 'estimate'}</span>
        </p>
      )}
      <p className={`${preview.price != null ? 'mt-1 ' : ''}text-xs text-slate-500`}>
        We’ll find {spec.name ? <strong className="font-medium text-slate-700">{spec.name}</strong> : 'this hotel'} on Google Hotels
        {spec.city ? ` in ${String(spec.city).split(',')[0]}` : ''} and watch its live price for {preview.subtitle || 'your stay'}.
      </p>
    </div>
  )
}
