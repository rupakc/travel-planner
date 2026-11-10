import { useId, useState } from 'react'
import { Link } from 'react-router-dom'
import { BellRing, Check, Loader2 } from 'lucide-react'
import { Trans, useTranslation } from 'react-i18next'
import { useAuth } from '../../context/AuthContext'
import { useAlerts } from '../../context/AlertsContext'
import { createFareWatch } from '../../services/api'
import { axiosErrorDetail } from '../../utils/httpError'
import { formatUsd } from '../../utils/fareCalendar'
import {
  checkTarget, defaultTarget, rangePosition, routeLabel,
} from '../../utils/fareWatch'
import { rangeLabel } from './localized'
import { track } from '../../utils/analytics'
import WatchDialogShell from './WatchDialogShell'
import { BrowserAlertsOffer, EmailOption, Option } from './WatchDialogParts'

/** Google's typical range for this trip with today's price marked on it. */
export function TypicalRangeBar({ range, price }) {
  const { t } = useTranslation('alerts')
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
        <span className="text-slate-600">{t(`range.${where}`, { low: formatUsd(range[0]), high: formatUsd(range[1]) })}</span>
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
  const { t } = useTranslation('alerts')
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
      setError(axiosErrorDetail(err).detail || t('dialog.fare.startFailed'))
    } finally {
      setSaving(false)
    }
  }

  const answer = (allow) => { answerBrowserAlerts(allow); setOfferBrowser(false) }

  return (
    <WatchDialogShell
      title={done ? (done.already_watching ? t('dialog.fare.already') : t('dialog.fare.watching')) : t('dialog.fare.watch')}
      subtitle={`${tripRoute} · ${rangeLabel(trip.departure_date, trip.return_date)}`}
      onClose={onClose}>
        {!done && (
          <form onSubmit={submit} className="px-5 pb-5">
            {price != null && (
              <div className="mt-3 rounded-xl bg-slate-50 px-4 py-3">
                <p className="text-sm text-slate-600">
                  {t('dialog.today')} <span className="text-2xl font-semibold tabular-nums text-slate-900">{formatUsd(price)}</span>
                  <span className="ml-1.5 text-xs text-slate-500">{t('travellersTotal', { count: trip.num_travelers })}</span>
                </p>
                <TypicalRangeBar range={insights?.typical_price_range} price={price} />
              </div>
            )}

            <fieldset className="mt-4 space-y-2">
              <legend className="mb-2 text-sm font-medium text-slate-700">{t('dialog.tellMe')}</legend>
              <Option name="mode" value="any_drop" checked={mode === 'any_drop'} onChange={() => setMode('any_drop')}
                title={t('dialog.anyDrop')}>
                <span className="block text-xs text-slate-500">{t('dialog.fare.anyDropHint')}</span>
              </Option>
              <Option name="mode" value="below_target" checked={mode === 'below_target'} onChange={() => setMode('below_target')}
                title={t('dialog.belowTarget')}>
                {mode === 'below_target' && (
                  <span className="mt-2 block">
                    <span className="flex items-center gap-2">
                      <span className="text-sm text-slate-500">$</span>
                      <input type="text" data-tid="alerts.dialog-target" inputMode="numeric" aria-label={t('dialog.fare.targetAria')} value={target}
                        onChange={e => { setTarget(e.target.value); setTargetTouched(true) }} aria-invalid={!!shownTargetError}
                        aria-describedby={`${titleId}-target`}
                        className="w-28 rounded-lg border border-slate-300 px-2.5 py-1.5 text-sm tabular-nums focus:border-sky-500 focus:outline-none focus:ring-2 focus:ring-sky-200" />
                      <span className="text-xs text-slate-500">{t('travellersTotal', { count: trip.num_travelers })}</span>
                    </span>
                    <span id={`${titleId}-target`} className={`mt-1 block text-xs ${shownTargetError ? 'text-red-600' : 'text-slate-500'}`}>
                      {shownTargetError || targetCheck.note || (insights?.typical_price_range ? t('dialog.fare.prefilled') : '')}
                    </span>
                  </span>
                )}
              </Option>
            </fieldset>

            <label className="mt-4 flex cursor-pointer items-start gap-3">
              <input type="checkbox" data-tid="alerts.dialog-flexible" checked={flexible} onChange={e => setFlexible(e.target.checked)}
                className="mt-0.5 h-4 w-4 rounded accent-sky-600" />
              <span>
                <span className="block text-sm font-medium text-slate-800">{t('edit.nearby')}</span>
                <span className="block text-xs text-slate-500">{t('dialog.fare.nearbyHint')}</span>
              </span>
            </label>

            {caps.email && <EmailOption checked={email} onChange={setEmail} email={user?.email} onClose={onClose} />}

            {error && <p role="alert" className="mt-4 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800">{error}</p>}

            <div className="mt-5 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <button type="button" data-tid="alerts.dialog-cancel" onClick={onClose}
                className="rounded-full px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100">{t('ui.cancel')}</button>
              <button type="submit" data-tid="alerts.dialog-start" disabled={saving || !!shownTargetError}
                className="inline-flex items-center justify-center gap-2 rounded-full bg-sky-600 px-5 py-2 text-sm font-semibold text-white hover:bg-sky-700 disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-500">
                {saving ? <Loader2 size={15} className="animate-spin" /> : <BellRing size={15} />}
                {saving ? t('dialog.fare.checking') : t('dialog.start')}
              </button>
            </div>
          </form>
        )}

        {done && <WatchConfirmation watch={done} offerBrowser={offerBrowser} onAnswer={answer} onClose={onClose} />}
    </WatchDialogShell>
  )
}

function WatchConfirmation({ watch, offerBrowser, onAnswer, onClose }) {
  const { t } = useTranslation('alerts')
  const price = watch.baseline_price ?? watch.last_price
  return (
    <div className="px-5 pb-5" role="status">
      <div className="mt-3 flex gap-3 rounded-xl bg-emerald-50 px-4 py-3 text-sm text-emerald-900">
        <Check size={18} className="mt-0.5 shrink-0 text-emerald-600" />
        <div>
          {price != null
            ? (
              <p>
                <Trans t={t} i18nKey="dialog.fare.todayFare"
                  values={{ price: formatUsd(price), travellers: t('travellersTotal', { count: watch.num_travelers }) }}
                  components={{ strong: <strong className="tabular-nums" /> }} />
              </p>
            )
            : <p>{t('dialog.fare.todayLater')}</p>}
          {watch.already_below_target && (
            <p className="mt-1.5 font-medium">{t('dialog.alreadyBelow')}</p>
          )}
          {!watch.already_below_target && watch.already_low && (
            <p className="mt-1.5 font-medium">{t('dialog.fare.alreadyLow')}</p>
          )}
        </div>
      </div>

      {offerBrowser && <BrowserAlertsOffer onAnswer={onAnswer} />}

      <div className="mt-5 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        <Link to={`/alerts?watch=${watch.id}`} data-tid="alerts.dialog-see-alerts" onClick={onClose}
          className="rounded-full px-4 py-2 text-center text-sm font-medium text-sky-700 hover:bg-sky-50">{t('dialog.seeAlerts')}</Link>
        <button type="button" data-tid="alerts.dialog-done" onClick={onClose}
          className="rounded-full bg-sky-600 px-5 py-2 text-sm font-semibold text-white hover:bg-sky-700">{t('ui.done')}</button>
      </div>
    </div>
  )
}
