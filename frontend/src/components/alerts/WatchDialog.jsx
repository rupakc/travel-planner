import { useId, useState } from 'react'
import { Link } from 'react-router-dom'
import { BellRing, Check, Loader2 } from 'lucide-react'
import { useAuth } from '../../context/AuthContext'
import { useAlerts } from '../../context/AlertsContext'
import { createFareWatch } from '../../services/api'
import { axiosErrorDetail } from '../../utils/httpError'
import { formatUsd } from '../../utils/fareCalendar'
import {
  checkTarget, defaultTarget, formatDateRange, rangePosition, routeLabel, travellersLabel,
} from '../../utils/fareWatch'
import { track } from '../../utils/analytics'
import WatchDialogShell from './WatchDialogShell'
import { BrowserAlertsOffer, EmailOption, Option } from './WatchDialogParts'

/** Google's typical range for this trip with today's price marked on it. */
export function TypicalRangeBar({ range, price }) {
  const pos = rangePosition(range, price)
  if (pos == null) return null
  const where = price < range[0] ? 'below' : price > range[1] ? 'above' : 'within'
  return (
    <div className="mt-3">
      <div className="relative h-1.5 rounded-full bg-gradient-to-r from-emerald-200 via-slate-200 to-amber-200">
        <span aria-hidden="true" style={{ left: `${pos}%` }}
          className="absolute top-1/2 h-3.5 w-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white bg-slate-800 shadow" />
      </div>
      <div className="mt-1.5 flex justify-between text-[11px] text-slate-500">
        <span>{formatUsd(range[0])}</span>
        <span className="text-slate-600">Today is {where} the usual {formatUsd(range[0])}–{formatUsd(range[1])}</span>
        <span>{formatUsd(range[1])}</span>
      </div>
    </div>
  )
}

/**
 * "Watch this fare": choose how to be told, then confirm. `trip` is the
 * search's (or saved plan's) trip; `price` / `insights` are what the page
 * already knows, so the dialog shows them without a lookup.
 */
export default function WatchDialog({ trip, price = null, insights = null, source = 'results', defaultFlexible = false, onClose, onWatched }) {
  const { token, user } = useAuth()
  const { caps, watchesChanged, shouldOfferBrowserAlerts, answerBrowserAlerts } = useAlerts()
  const titleId = useId()
  const [mode, setMode] = useState('any_drop')
  const [target, setTarget] = useState(() => String(defaultTarget(insights, price)))
  const [flexible, setFlexible] = useState(defaultFlexible)
  const [email, setEmail] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const [done, setDone] = useState(null)       // the created (or existing) watch
  const [offerBrowser, setOfferBrowser] = useState(false)
  const [targetTouched, setTargetTouched] = useState(false)

  const targetCheck = mode === 'below_target' ? checkTarget(target, price) : { error: null, note: null }
  // Speak up about the target only once it's been typed in (or submitted)
  const shownTargetError = targetTouched ? targetCheck.error : null
  const hasEmail = !!user?.email
  const tripRoute = routeLabel({ origin_label: trip.origin, destination_label: trip.destination })

  const submit = async (e) => {
    e.preventDefault()
    if (targetCheck.error) { setTargetTouched(true); return }
    setSaving(true)
    setError(null)
    try {
      const watch = await createFareWatch({
        ...trip,
        alert_mode: mode,
        target_price: mode === 'below_target' ? targetCheck.value : null,
        flexible_days: flexible ? 3 : 0,
        email_enabled: email && hasEmail && caps.email,
      }, token)
      track('watch_created', source, { mode, flex: flexible, email, already: !!watch.already_watching })
      watchesChanged()
      setDone(watch)
      setOfferBrowser(!watch.already_watching && shouldOfferBrowserAlerts())
      onWatched?.(watch)
    } catch (err) {
      setError(axiosErrorDetail(err).detail || 'Couldn’t start watching this fare. Try again in a moment.')
    } finally {
      setSaving(false)
    }
  }

  const answer = (allow) => { answerBrowserAlerts(allow); setOfferBrowser(false) }

  return (
    <WatchDialogShell
      title={done ? (done.already_watching ? 'You’re already watching this fare' : 'Watching this fare') : 'Watch this fare'}
      subtitle={`${tripRoute} · ${formatDateRange(trip.departure_date, trip.return_date)}`}
      onClose={onClose}>
        {!done && (
          <form onSubmit={submit} className="px-5 pb-5">
            {price != null && (
              <div className="mt-3 rounded-xl bg-slate-50 px-4 py-3">
                <p className="text-sm text-slate-600">
                  Today <span className="text-2xl font-semibold tabular-nums text-slate-900">{formatUsd(price)}</span>
                  <span className="ml-1.5 text-xs text-slate-500">{travellersLabel(trip.num_travelers)}</span>
                </p>
                <TypicalRangeBar range={insights?.typical_price_range} price={price} />
              </div>
            )}

            <fieldset className="mt-4 space-y-2">
              <legend className="mb-2 text-sm font-medium text-slate-700">Tell me</legend>
              <Option name="mode" value="any_drop" checked={mode === 'any_drop'} onChange={() => setMode('any_drop')}
                title="When the price drops">
                <span className="block text-xs text-slate-500">Only meaningful drops — at least $15 and 5%. Never more than once a day.</span>
              </Option>
              <Option name="mode" value="below_target" checked={mode === 'below_target'} onChange={() => setMode('below_target')}
                title="When it’s below a price I choose">
                {mode === 'below_target' && (
                  <span className="mt-2 block">
                    <span className="flex items-center gap-2">
                      <span className="text-sm text-slate-500">$</span>
                      <input type="text" inputMode="numeric" aria-label="Target price in US dollars" value={target}
                        onChange={e => { setTarget(e.target.value); setTargetTouched(true) }} aria-invalid={!!shownTargetError}
                        aria-describedby={`${titleId}-target`}
                        className="w-28 rounded-lg border border-slate-300 px-2.5 py-1.5 text-sm tabular-nums focus:border-sky-500 focus:outline-none focus:ring-2 focus:ring-sky-200" />
                      <span className="text-xs text-slate-500">{travellersLabel(trip.num_travelers)}</span>
                    </span>
                    <span id={`${titleId}-target`} className={`mt-1 block text-xs ${shownTargetError ? 'text-red-600' : 'text-slate-500'}`}>
                      {shownTargetError || targetCheck.note || (insights?.typical_price_range ? 'Pre-filled with the low end of the usual price.' : '')}
                    </span>
                  </span>
                )}
              </Option>
            </fieldset>

            <label className="mt-4 flex cursor-pointer items-start gap-3">
              <input type="checkbox" checked={flexible} onChange={e => setFlexible(e.target.checked)}
                className="mt-0.5 h-4 w-4 rounded accent-sky-600" />
              <span>
                <span className="block text-sm font-medium text-slate-800">Include nearby dates (±3 days)</span>
                <span className="block text-xs text-slate-500">We’ll also tell you if leaving a few days earlier or later saves at least $25, keeping the same trip length.</span>
              </span>
            </label>

            {caps.email && <EmailOption checked={email} onChange={setEmail} email={user?.email} onClose={onClose} />}

            {error && <p role="alert" className="mt-4 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800">{error}</p>}

            <div className="mt-5 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <button type="button" onClick={onClose}
                className="rounded-full px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100">Cancel</button>
              <button type="submit" disabled={saving || !!shownTargetError}
                className="inline-flex items-center justify-center gap-2 rounded-full bg-sky-600 px-5 py-2 text-sm font-semibold text-white hover:bg-sky-700 disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-500">
                {saving ? <Loader2 size={15} className="animate-spin" /> : <BellRing size={15} />}
                {saving ? 'Checking today’s price…' : 'Start watching'}
              </button>
            </div>
          </form>
        )}

        {done && <WatchConfirmation watch={done} offerBrowser={offerBrowser} onAnswer={answer} onClose={onClose} />}
    </WatchDialogShell>
  )
}

function WatchConfirmation({ watch, offerBrowser, onAnswer, onClose }) {
  const price = watch.baseline_price ?? watch.last_price
  return (
    <div className="px-5 pb-5" role="status">
      <div className="mt-3 flex gap-3 rounded-xl bg-emerald-50 px-4 py-3 text-sm text-emerald-900">
        <Check size={18} className="mt-0.5 shrink-0 text-emerald-600" />
        <div>
          {price != null
            ? <p>Today’s fare is <strong className="tabular-nums">{formatUsd(price)}</strong> ({travellersLabel(watch.num_travelers)}). We’ll check about twice a day and only speak up when it’s worth it.</p>
            : <p>We’ll take today’s price shortly, then check about twice a day and only speak up when it’s worth it.</p>}
          {watch.already_below_target && (
            <p className="mt-1.5 font-medium">Already below your target — we’ll tell you if it drops further.</p>
          )}
          {!watch.already_below_target && watch.already_low && (
            <p className="mt-1.5 font-medium">Google already rates this as a low price — we’ll tell you if it drops further.</p>
          )}
        </div>
      </div>

      {offerBrowser && <BrowserAlertsOffer onAnswer={onAnswer} />}

      <div className="mt-5 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        <Link to={`/alerts?watch=${watch.id}`} onClick={onClose}
          className="rounded-full px-4 py-2 text-center text-sm font-medium text-sky-700 hover:bg-sky-50">See your alerts</Link>
        <button type="button" onClick={onClose}
          className="rounded-full bg-sky-600 px-5 py-2 text-sm font-semibold text-white hover:bg-sky-700">Done</button>
      </div>
    </div>
  )
}
