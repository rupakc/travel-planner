import { ExternalLink, Star } from 'lucide-react'
import {
  formatPrice, perPerson, providerName, titleDiffers, watchCurrency,
} from '../../../utils/activityWatch'

const people = (n) => (n === 1 ? '1 traveller' : `${n} travellers`)

function dayLabel(iso) {
  const d = new Date(`${iso}T12:00:00`)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' })
}

/**
 * Activity body of the price-watch dialog. Before matching: what we'll look
 * for and the AI estimate, labelled. Once watched: the matched GetYourGuide /
 * Viator listing (provider as text), its rating, "from $X per person" ×
 * travellers, a link to it and where the price comes from. Money is always
 * in the watch's own currency once there is a watch (a picked suggestion may
 * differ from what the page showed).
 */
export default function ActivityDialogBody({ spec = {}, watch = null }) {
  if (watch) return <Matched watch={watch} />
  const n = spec.travellers || 1
  if (spec.listing_url) {
    return (
      <div className="mt-3 rounded-xl bg-slate-50 px-4 py-3 text-sm text-slate-600">
        <p>
          We’ll watch the listing you picked for <strong className="text-slate-800">{spec.name}</strong>
          {n > 1 ? `, for ${people(n)}` : ''}.
        </p>
        <a href={spec.listing_url} target="_blank" rel="noopener noreferrer"
          className="mt-1 inline-flex items-center gap-1 text-xs font-medium text-sky-700 underline-offset-2 hover:underline">
          <ExternalLink size={11} aria-hidden="true" /> See the listing
        </a>
      </div>
    )
  }
  return (
    <div className="mt-3 rounded-xl bg-slate-50 px-4 py-3 text-sm text-slate-600">
      <p>
        We’ll look for <strong className="text-slate-800">{spec.name}</strong>
        {spec.city ? ` in ${spec.city}` : ''} on GetYourGuide and Viator and watch its “from” price per person
        {n > 1 ? `, for ${people(n)}` : ''}.
      </p>
      {spec.date && <p className="mt-1 text-xs text-slate-500">For {dayLabel(spec.date)} — we stop checking after that day.</p>}
      {spec.estimate_price != null && (
        <p className="mt-1.5 text-xs text-slate-500">
          AI estimate: <span className="tabular-nums">{formatPrice(spec.estimate_price, 'USD')}</span> per person — an estimate, not a live price.
        </p>
      )}
    </div>
  )
}

function Matched({ watch }) {
  const subject = watch.subject || {}
  const obs = watch.last_observation || {}
  const observed = obs.observed || {}
  const currency = watchCurrency(watch)
  const provider = providerName(subject.provider || observed.provider)
  const title = subject.listing_title || watch.title
  const link = watch.link || obs.link || subject.listing_url
  const n = subject.travellers || 1
  const unit = perPerson(watch)
  const total = watch.last_price ?? watch.baseline_price
  const money = (v) => formatPrice(v, currency)
  return (
    <div className="rounded-xl border border-emerald-100 bg-white px-3 py-2.5 text-slate-700">
      <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{provider}</p>
      <p className="text-sm font-semibold text-slate-900">{title}</p>
      {observed.rating != null && (
        <p className="mt-0.5 flex items-center gap-1 text-xs text-slate-500">
          <Star size={11} className="fill-amber-400 text-amber-400" aria-hidden="true" />
          <span>{observed.rating}{observed.reviews ? ` · ${observed.reviews.toLocaleString('en-US')} reviews` : ''}</span>
        </p>
      )}
      {unit != null && (
        <p className="mt-1.5 text-sm tabular-nums">
          from <strong>{money(unit)}</strong> per person
          {n > 1 && total != null && <> × {people(n)} = <strong>{money(total)}</strong></>}
        </p>
      )}
      {titleDiffers(subject.name, title) && (
        <p className="mt-1.5 text-xs text-amber-800">
          This is the closest listing we found for “{subject.name}”. Check it’s the one you want.
        </p>
      )}
      <p className="mt-1.5 text-[11px] text-slate-500">
        Price as shown in Google results for {provider} — the listing’s lowest “from” price; your date and options may cost more.
        {currency !== 'USD' && ` Prices are in ${currency}, as the listing shows them.`}
      </p>
      {link && (
        <a href={link} target="_blank" rel="noopener noreferrer"
          className="mt-1.5 inline-flex items-center gap-1 text-xs font-medium text-sky-700 underline-offset-2 hover:underline">
          <ExternalLink size={11} aria-hidden="true" /> See it on {provider}
        </a>
      )}
    </div>
  )
}
