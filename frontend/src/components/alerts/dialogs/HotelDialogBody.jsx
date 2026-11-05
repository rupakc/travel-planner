import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import { useAuth } from '../../../context/AuthContext'
import { useAlerts } from '../../../context/AlertsContext'
import { createPriceWatch, deletePriceWatch } from '../../../services/api'
import { matchedElsewhere } from '../../../utils/hotelWatch'
import { formatPrice, priceWatchBody, priceWatchLink } from '../../../utils/priceWatch'

const nightsOf = (ci, co) => Math.round((Date.parse(co) - Date.parse(ci)) / 86400000)

/**
 * Hotel body of the price-watch dialog. Before: the AI price the page showed
 * (labelled as an estimate, with what it covers) and the stay we'll look up.
 * After: the Google Hotels property actually tracked, its live total and
 * nightly rate, a note when Google lists it under another name than the
 * card, and "Not this one?" — the other priced properties the search found,
 * any of which replaces the watch (same alert settings) and is reported
 * through `onReplaced(newWatch, { spec })` so the dialog follows it. Offered
 * once: after a swap the list is gone.
 */
export default function HotelDialogBody({ spec = {}, preview = {}, watch = null, unitLabel = null, onClose, onReplaced }) {
  if (watch) return <Tracked watch={watch} unitLabel={unitLabel} onClose={onClose} onReplaced={onReplaced} />
  return (
    <div className="mt-3 rounded-xl bg-slate-50 px-4 py-3">
      {preview.estimate != null && (
        <p className="text-sm text-slate-600">
          Shown now <span className="text-2xl font-semibold tabular-nums text-slate-900">{formatPrice(preview.estimate, preview.currency)}</span>
          <span className="ml-1.5 text-xs text-slate-500">{preview.estimateLabel || 'AI estimate'}</span>
        </p>
      )}
      <p className={`${preview.estimate != null ? 'mt-1 ' : ''}text-xs text-slate-500`}>
        We’ll find {spec.name ? <strong className="font-medium text-slate-700">{spec.name}</strong> : 'this hotel'} on Google Hotels
        {spec.city ? ` in ${String(spec.city).split(',')[0]}` : ''} and watch its live price for {preview.subtitle || 'your stay'}.
      </p>
    </div>
  )
}

/** The hotel spec that watches `watch`'s property again (same stay). */
function specOf(watch) {
  const s = watch.subject || {}
  return {
    name: s.requested_name || watch.title, city: s.city, check_in: s.check_in, check_out: s.check_out,
    adults: s.adults, rooms: s.rooms, property_token: s.property_token,
  }
}

function Tracked({ watch: created, unitLabel, onClose, onReplaced }) {
  const { token } = useAuth()
  const { watchesChanged } = useAlerts()
  const [watch, setWatch] = useState(created)
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(null)
  const [error, setError] = useState(null)
  const [swapped, setSwapped] = useState(false)
  const obs = watch.last_observation || {}
  const s = watch.subject || {}
  const total = watch.baseline_price ?? watch.last_price
  const nights = s.check_in && s.check_out ? nightsOf(s.check_in, s.check_out) : null
  const alternatives = swapped ? [] : (obs.observed?.alternatives || [])

  const settings = {
    alert_mode: watch.alert_mode, target_price: watch.target_price ?? null, email_enabled: !!watch.email_enabled,
  }
  const create = (hotelSpec) => createPriceWatch(priceWatchBody('hotel', hotelSpec, settings), token)
  const switched = (next, nextSpec) => {
    watchesChanged()
    setWatch(next)
    setSwapped(true)
    setOpen(false)
    onReplaced?.(next, { spec: nextSpec })
  }

  // Create the replacement first: if it fails, the traveller keeps the first
  // watch. At the active-watch limit (409) make room first, and put the first
  // watch back (same property, same settings) if the new one then fails.
  const swap = async (alt, i) => {
    setBusy(i)
    setError(null)
    try {
      let next
      try {
        next = await create(alt.spec)
      } catch (err) {
        if (err?.response?.status !== 409) throw err
        await deletePriceWatch(watch.id, token)
        try {
          next = await create(alt.spec)
        } catch {
          const firstSpec = specOf(watch)
          const back = await create(firstSpec).catch(() => null)
          watchesChanged()
          if (back) {
            setWatch(back)
            onReplaced?.(back, { spec: firstSpec })
            setError('Couldn’t switch to that hotel — you’re still watching the first one.')
          } else {
            setError('Couldn’t switch to that hotel, and the first one couldn’t be put back — watch it again from its card.')
          }
          return
        }
        switched(next, alt.spec)
        return
      }
      await deletePriceWatch(watch.id, token)
      switched(next, alt.spec)
    } catch {
      setError('Couldn’t switch to that hotel — you’re still watching the first one.')
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="text-sm text-slate-700">
      <p>Tracking: <strong className="text-slate-900">{watch.title}</strong> on Google Hotels</p>
      <p className="mt-1 text-xs text-slate-600 tabular-nums">
        {formatPrice(total, watch.currency)}{nights ? ` for ${nights} night${nights === 1 ? '' : 's'}` : ''}
        {obs.unit_price != null ? ` · ${formatPrice(obs.unit_price, watch.currency)} ${unitLabel || 'a night'}` : ''}
        {watch.subtitle ? ` · ${watch.subtitle}` : ''}
      </p>
      {matchedElsewhere(watch) && (
        <p className="mt-1.5 text-xs text-slate-600">
          Your plan calls it “{s.requested_name}”; Google Hotels lists it as “{watch.title}”.
          {alternatives.length === 0 && (
            <> Not this one? <Link to={priceWatchLink(watch)} onClick={onClose}
              className="font-medium text-sky-700 underline underline-offset-2 hover:text-sky-900">Remove it on your Alerts page</Link>.</>
          )}
        </p>
      )}
      {alternatives.length > 0 && (
        <div className="mt-2">
          <button type="button" aria-expanded={open} onClick={() => setOpen(v => !v)}
            className="text-xs font-semibold text-sky-700 underline underline-offset-2 hover:text-sky-900">Not this one?</button>
          {open && (
            <ul className="mt-2 space-y-2" aria-label="Other hotels on Google Hotels">
              {alternatives.map((alt, i) => (
                <li key={alt.spec?.property_token || i} className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-white px-3 py-2">
                  <span className="min-w-0">
                    <span className="block text-sm font-medium text-slate-800">{alt.title}</span>
                    {alt.subtitle && <span className="block text-xs text-slate-500">{alt.subtitle}</span>}
                  </span>
                  <span className="flex items-center gap-2">
                    {alt.price != null && <span className="text-sm font-semibold tabular-nums text-slate-900">{formatPrice(alt.price, alt.currency)}</span>}
                    <button type="button" disabled={busy != null} onClick={() => swap(alt, i)}
                      className="inline-flex items-center gap-1 rounded-full border border-sky-300 bg-white px-3 py-1 text-xs font-semibold text-sky-700 hover:bg-sky-50 disabled:opacity-60">
                      {busy === i && <Loader2 size={12} className="animate-spin" />} Watch this instead
                    </button>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      {error && <p role="alert" className="mt-2 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800">{error}</p>}
    </div>
  )
}
