import { useId, useState } from 'react'
import { Link } from 'react-router-dom'
import { BellRing, Check, Loader2 } from 'lucide-react'
import { useAuth } from '../../context/AuthContext'
import { useAlerts } from '../../context/AlertsContext'
import { createPriceWatch } from '../../services/api'
import { axiosErrorDetail } from '../../utils/httpError'
import { defaultTarget } from '../../utils/fareWatch'
import {
  checkPriceTarget, currencyLabel, currencySymbol, formatPrice, kindNoun, priceWatchBody, priceWatchLink,
} from '../../utils/priceWatch'
import { track } from '../../utils/analytics'
import WatchDialogShell from './WatchDialogShell'
import { BrowserAlertsOffer, EmailOption, Option } from './WatchDialogParts'
import { dialogBodyFor } from './dialogs'

/** The API's 422 "no live price" answer, or null for any other error. */
function noLivePrice(err) {
  const data = err?.response?.data
  return err?.response?.status === 422 && data?.code === 'no_live_price' ? data : null
}

function Suggestions({ result, busy, onPick }) {
  return (
    <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50/60 px-4 py-3" role="alert">
      <p className="text-sm font-medium text-amber-900">{result.message}</p>
      {result.estimate?.price != null && (
        <p className="mt-1 text-xs text-amber-800">Our AI estimate was {formatPrice(result.estimate.price, result.estimate.currency)} — an estimate, not a live price, so we can’t watch it.</p>
      )}
      {result.suggestions?.length > 0 && (
        <>
          <p className="mt-3 text-xs font-medium text-slate-600">Live prices we did find:</p>
          <ul className="mt-1.5 space-y-2">
            {result.suggestions.map((s, i) => (
              <li key={i} className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-white px-3 py-2">
                <span className="min-w-0">
                  <span className="block text-sm font-medium text-slate-800">{s.title}</span>
                  {s.subtitle && <span className="block text-xs text-slate-500">{s.subtitle}</span>}
                </span>
                <span className="flex items-center gap-2">
                  {s.price != null && <span className="text-sm font-semibold tabular-nums text-slate-900">{formatPrice(s.price, s.currency)}</span>}
                  <button type="button" disabled={busy} onClick={() => onPick(s)}
                    className="rounded-full border border-sky-300 bg-white px-3 py-1 text-xs font-semibold text-sky-700 hover:bg-sky-50 disabled:opacity-60">
                    Watch this instead
                  </button>
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}

/**
 * "Watch this price" for a hotel, an activity or a whole trip. `spec` is
 * sent as-is under its kind (the backend source matches it to a live
 * price); `preview` is what the page already shows ({ title, subtitle,
 * price, priceLabel, currency }); `unitLabel` ("per night", "per person")
 * is passed to the kind's body, which comes from ./dialogs.
 *
 * After a "no live price" answer the traveller may pick a suggestion, which
 * is a different subject: `onWatched(watch, { spec: usedSpec, viaSuggestion })`
 * says which spec was watched, so a caller marks its own subject as watched
 * only when `viaSuggestion` is false. The done state shows the created
 * watch's own title and subtitle, and bodies always get the spec used.
 */
export default function PriceWatchDialog({ kind, spec, preview = {}, unitLabel = null, source = 'results', onClose, onWatched }) {
  const { token, user } = useAuth()
  const { caps, watchesChanged, shouldOfferBrowserAlerts, answerBrowserAlerts } = useAlerts()
  const fieldId = useId()
  const Body = dialogBodyFor(kind)
  const [mode, setMode] = useState('any_drop')
  const [target, setTarget] = useState(() => String(defaultTarget(null, preview.price)))
  const [targetTouched, setTargetTouched] = useState(false)
  const [email, setEmail] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const [noMatch, setNoMatch] = useState(null)
  const [done, setDone] = useState(null)
  const [usedSpec, setUsedSpec] = useState(spec)
  const [offerBrowser, setOfferBrowser] = useState(false)
  const noun = kindNoun(kind)
  const currency = preview.currency || 'USD'
  const targetCheck = mode === 'below_target' ? checkPriceTarget(target) : { error: null }
  const shownTargetError = targetTouched ? targetCheck.error : null

  const create = async (watchSpec) => {
    if (targetCheck.error) { setTargetTouched(true); return }
    setSaving(true)
    setError(null)
    try {
      const watch = await createPriceWatch(priceWatchBody(kind, watchSpec, {
        alert_mode: mode,
        target_price: mode === 'below_target' ? targetCheck.value : null,
        email_enabled: email && !!user?.email && caps.email,
      }), token)
      const viaSuggestion = watchSpec !== spec
      track('price_watch_created', source, { kind, mode, email, already: !!watch.already_watching, viaSuggestion })
      watchesChanged()
      setNoMatch(null)
      setUsedSpec(watchSpec)
      setDone(watch)
      setOfferBrowser(!watch.already_watching && shouldOfferBrowserAlerts())
      onWatched?.(watch, { spec: watchSpec, viaSuggestion })
    } catch (err) {
      const nlp = noLivePrice(err)
      if (nlp) setNoMatch(nlp)
      else setError(axiosErrorDetail(err).detail || `Couldn’t start watching this ${noun}. Try again in a moment.`)
    } finally {
      setSaving(false)
    }
  }

  const title = done
    ? (done.already_watching ? `You’re already watching this ${noun}` : `Watching this ${noun}`)
    : `Watch this ${noun}`
  const subtitle = (done ? [done.title, done.subtitle] : [preview.title, preview.subtitle]).filter(Boolean).join(' · ')

  return (
    <WatchDialogShell title={title} subtitle={subtitle} onClose={onClose}>
      {!done && (
        <form onSubmit={e => { e.preventDefault(); if (!noMatch) create(spec) }} className="px-5 pb-5">
          <Body kind={kind} spec={usedSpec} preview={preview} watch={null} unitLabel={unitLabel} onClose={onClose} />

          <fieldset className="mt-4 space-y-2">
            <legend className="mb-2 text-sm font-medium text-slate-700">Tell me</legend>
            <Option name="pmode" value="any_drop" checked={mode === 'any_drop'} onChange={() => setMode('any_drop')}
              title="When the price drops">
              <span className="block text-xs text-slate-500">Only meaningful drops. Never more than once a day.</span>
            </Option>
            <Option name="pmode" value="below_target" checked={mode === 'below_target'} onChange={() => setMode('below_target')}
              title="When it’s below a price I choose">
              {mode === 'below_target' && (
                <span className="mt-2 block">
                  <span className="flex items-center gap-2">
                    <span className="text-sm text-slate-500">{currencySymbol(currency)}</span>
                    <input type="text" inputMode="numeric" aria-label={`Target price in ${currencyLabel(currency)}`} value={target}
                      onChange={e => { setTarget(e.target.value); setTargetTouched(true) }} aria-invalid={!!shownTargetError}
                      aria-describedby={`${fieldId}-target`}
                      className="w-28 rounded-lg border border-slate-300 px-2.5 py-1.5 text-sm tabular-nums focus:border-sky-500 focus:outline-none focus:ring-2 focus:ring-sky-200" />
                  </span>
                  <span id={`${fieldId}-target`} className={`mt-1 block text-xs ${shownTargetError ? 'text-red-600' : 'text-slate-500'}`}>
                    {shownTargetError || `The total price, in ${currencyLabel(currency)}.`}
                  </span>
                </span>
              )}
            </Option>
          </fieldset>

          {caps.email && <EmailOption checked={email} onChange={setEmail} email={user?.email} onClose={onClose} />}

          {noMatch && <Suggestions result={noMatch} busy={saving} onPick={(s) => create(s.spec)} />}
          {error && <p role="alert" className="mt-4 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800">{error}</p>}

          <div className="mt-5 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <button type="button" onClick={onClose}
              className="rounded-full px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100">Cancel</button>
            {!noMatch && <button type="submit" disabled={saving || !!shownTargetError}
              className="inline-flex items-center justify-center gap-2 rounded-full bg-sky-600 px-5 py-2 text-sm font-semibold text-white hover:bg-sky-700 disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-500">
              {saving ? <Loader2 size={15} className="animate-spin" /> : <BellRing size={15} />}
              {saving ? 'Finding the live price…' : 'Start watching'}
            </button>}
          </div>
        </form>
      )}

      {done && (
        <div className="px-5 pb-5" role="status">
          <div className="mt-3 flex gap-3 rounded-xl bg-emerald-50 px-4 py-3 text-sm text-emerald-900">
            <Check size={18} className="mt-0.5 shrink-0 text-emerald-600" />
            <div className="min-w-0">
              {(done.baseline_price ?? done.last_price) != null
                ? <p>The live price is <strong className="tabular-nums">{formatPrice(done.baseline_price ?? done.last_price, done.currency)}</strong>. We’ll check about twice a day and only speak up when it’s worth it.</p>
                : <p>We’ll take the live price shortly, then check about twice a day and only speak up when it’s worth it.</p>}
              {done.already_below_target && (
                <p className="mt-1.5 font-medium">Already below your target — we’ll tell you if it drops further.</p>
              )}
              <div className="mt-2"><Body kind={kind} spec={usedSpec} preview={preview} watch={done} unitLabel={unitLabel} onClose={onClose} /></div>
            </div>
          </div>
          {offerBrowser && <BrowserAlertsOffer onAnswer={(allow) => { answerBrowserAlerts(allow); setOfferBrowser(false) }} />}
          <div className="mt-5 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <Link to={priceWatchLink(done)} onClick={onClose}
              className="rounded-full px-4 py-2 text-center text-sm font-medium text-sky-700 hover:bg-sky-50">See your alerts</Link>
            <button type="button" onClick={onClose}
              className="rounded-full bg-sky-600 px-5 py-2 text-sm font-semibold text-white hover:bg-sky-700">Done</button>
          </div>
        </div>
      )}
    </WatchDialogShell>
  )
}
