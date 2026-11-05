import { formatUsd } from '../../../utils/fareCalendar'

/**
 * Default body of the price-watch dialog. Every body gets
 * `{ kind, spec, preview, watch }`: `spec` is what will be matched,
 * `preview` what the page already knows ({ title, subtitle, price,
 * priceLabel }), and `watch` the created watch once there is one (show the
 * matched subject so the traveller sees what is tracked).
 */
export default function GenericPriceBody({ preview = {}, watch = null }) {
  if (watch) {
    const unit = watch.last_observation?.unit_price
    return (
      <p className="text-sm text-slate-600">
        Tracking <strong className="text-slate-800">{watch.title}</strong>
        {watch.subtitle ? ` · ${watch.subtitle}` : ''}
        {unit != null ? ` · ${formatUsd(unit)} per unit` : ''}
      </p>
    )
  }
  if (preview.price == null) return null
  return (
    <div className="mt-3 rounded-xl bg-slate-50 px-4 py-3">
      <p className="text-sm text-slate-600">
        Shown now <span className="text-2xl font-semibold tabular-nums text-slate-900">{formatUsd(preview.price)}</span>
        {preview.priceLabel && <span className="ml-1.5 text-xs text-slate-500">{preview.priceLabel}</span>}
      </p>
      <p className="mt-1 text-xs text-slate-500">We’ll look up the live price when you start watching.</p>
    </div>
  )
}
