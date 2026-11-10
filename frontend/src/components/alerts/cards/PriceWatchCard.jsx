import { useRef, useState } from 'react'
import { ExternalLink, Loader2, Pause, Pencil, Play, RefreshCw, Trash2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { watchStatus } from '../../../utils/fareWatch'
import {
  checkPriceTarget, currencyLabel, currencySymbol, formatPrice, isUnavailable, priceWatchChange, watchDomId,
} from '../../../utils/priceWatch'
import Sparkline from '../Sparkline'
import { agoLabel, changeText, statusLabel, untilLabel } from '../localized'
import { LiveCheckButton, LiveCheckPanel, useLiveCheck } from '../LiveCheck'

const CHIP = {
  sky: 'bg-sky-50 text-sky-800 border-sky-200',
  emerald: 'bg-emerald-50 text-emerald-800 border-emerald-200',
  slate: 'bg-slate-100 text-slate-600 border-slate-200',
  amber: 'bg-amber-50 text-amber-800 border-amber-200',
}
const quiet = 'inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-100 hover:text-slate-800 disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-500'

function EditPanel({ watch, emailAvailable, hasEmail, onSave, onCancel }) {
  const { t } = useTranslation('alerts')
  const [mode, setMode] = useState(watch.alert_mode)
  // The exact target ("9.5", not "10"): saving other settings never moves it
  const initialTarget = watch.target_price != null ? String(watch.target_price) : ''
  const [target, setTarget] = useState(initialTarget)
  const [email, setEmail] = useState(!!watch.email_enabled)
  const [saving, setSaving] = useState(false)
  const check = mode === 'below_target' ? checkPriceTarget(target) : { error: null }
  const save = async (e) => {
    e.preventDefault()
    if (check.error) return
    setSaving(true)
    const changes = { alert_mode: mode, email_enabled: email }
    if (mode === 'below_target' && (target !== initialTarget || watch.target_price == null)) {
      changes.target_price = check.value
    }
    await onSave(changes)
    setSaving(false)
  }
  return (
    <form onSubmit={save} className="mt-4 space-y-3 rounded-xl bg-slate-50 p-4" aria-label={t('edit.aria')}>
      <fieldset className="space-y-1.5">
        <legend className="mb-1 text-xs font-medium text-slate-600">{t('edit.tellMe')}</legend>
        <label className="flex items-center gap-2 text-sm text-slate-700">
          <input type="radio" data-tid="alerts.edit-any-drop" name={`pmode-${watch.id}`} checked={mode === 'any_drop'} onChange={() => setMode('any_drop')} className="accent-sky-600" />
          {t('edit.whenDrops')}
        </label>
        <label className="flex flex-wrap items-center gap-2 text-sm text-slate-700">
          <input type="radio" data-tid="alerts.edit-below-target" name={`pmode-${watch.id}`} checked={mode === 'below_target'} onChange={() => setMode('below_target')} className="accent-sky-600" />
          {t('edit.belowSymbol', { symbol: currencySymbol(watch.currency) })}
          <input type="text" data-tid="alerts.edit-target" inputMode="numeric" value={target} onChange={e => { setTarget(e.target.value); setMode('below_target') }}
            aria-label={t('edit.target', { currency: currencyLabel(watch.currency) })} aria-invalid={!!check.error}
            className="w-24 rounded-lg border border-slate-300 px-2 py-1 text-sm tabular-nums focus:border-sky-500 focus:outline-none focus:ring-2 focus:ring-sky-200" />
        </label>
        {check.error && <p className="text-xs text-red-600">{check.error}</p>}
      </fieldset>
      {emailAvailable && (
        <label className={`flex items-center gap-2 text-sm ${hasEmail ? 'text-slate-700' : 'text-slate-400'}`}>
          <input type="checkbox" data-tid="alerts.edit-email" checked={email && hasEmail} disabled={!hasEmail} onChange={e => setEmail(e.target.checked)} className="accent-sky-600" />
          {t('edit.alsoEmail')}{!hasEmail && ` ${t('edit.noEmailHint')}`}
        </label>
      )}
      <div className="flex justify-end gap-2">
        <button type="button" data-tid="alerts.edit-cancel" onClick={onCancel} className={quiet}>{t('ui.cancel')}</button>
        <button type="submit" data-tid="alerts.edit-save" disabled={saving || !!check.error}
          className="inline-flex items-center gap-1.5 rounded-full bg-sky-600 px-4 py-1.5 text-xs font-semibold text-white hover:bg-sky-700 disabled:opacity-60">
          {saving && <Loader2 size={12} className="animate-spin" />} {t('ui.save')}
        </button>
      </div>
    </form>
  )
}

/**
 * One watched hotel / activity / trip price — the default card for every
 * price-watch kind (see ./index.js). Kind cards can reuse it, passing:
 * - `Details`: component rendered under the price ({ watch }), e.g. a trip
 *   breakdown or the matched hotel's nightly rate;
 * - `openLabel`: wording of the listing link (default "Open listing");
 * - `unitLabel`: wording after the unit price (default "per unit");
 * - `unavailableText`: what to say while it isn't available for the dates.
 * Actions call back up (as WatchCard): `busy` names the action in flight
 * ('check' | 'save' | 'delete' | 'status'), `message` the latest outcome.
 */
export default function PriceWatchCard({
  watch, highlighted = false, busy = null, message = null, emailAvailable = false, hasEmail = false,
  onCheck, onUpdate, onDelete, onLiveCheck = null, onOpen, now = new Date(), Details = null,
  openLabel: openLabelProp = null, unitLabel: unitLabelProp = null, unavailableText: unavailableProp = null,
}) {
  const { t } = useTranslation('alerts')
  const openLabel = openLabelProp || t('card.openListing')
  const unitLabel = unitLabelProp || t('unit.unit')
  const unavailableText = unavailableProp || t('card.unavailable')
  const [editing, setEditing] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const live = useLiveCheck(onLiveCheck)
  const liveButton = useRef(null)
  const status = watchStatus(watch)
  const change = priceWatchChange(watch)
  const money = (v) => formatPrice(v, watch.currency)
  const past = watch.status === 'expired'
  const price = watch.last_price ?? watch.baseline_price
  const target = watch.alert_mode === 'below_target' ? watch.target_price : null
  const unit = watch.last_observation?.unit_price
  const domId = watchDomId(watch)
  const link = watch.link || watch.last_observation?.link

  return (
    <article id={domId} aria-labelledby={`${domId}-title`}
      className={`scroll-mt-24 rounded-2xl border bg-white/90 p-4 backdrop-blur-sm transition-shadow sm:p-5 ${highlighted ? 'border-sky-300 ring-2 ring-sky-200' : 'border-white/60'} ${past ? 'opacity-80' : ''}`}>
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 id={`${domId}-title`} className="font-display text-lg font-semibold text-slate-900">{watch.title}</h3>
            <span className={`rounded-full border px-2 py-0.5 text-[11px] font-medium ${CHIP[status.tone]}`}>{statusLabel(status)}</span>
          </div>
          {watch.subtitle && <p className="mt-0.5 text-sm text-slate-500">{watch.subtitle}</p>}
          <p className="mt-0.5 text-xs text-slate-400">
            {target != null ? t('card.alertsTarget', { price: money(target) }) : t('card.alertsDrops')}
            {watch.email_enabled ? ` · ${t('card.alsoEmail')}` : ''}
          </p>
        </div>
        <div className="sm:text-right">
          {price != null ? (
            <>
              <p className="text-3xl font-semibold leading-none tabular-nums text-slate-900">{money(price)}</p>
              {unit != null && <p className="mt-1 text-[11px] text-slate-400">{money(unit)} {unitLabel}</p>}
              {change && change.direction !== 'same' && (
                <p className={`mt-1 text-xs font-medium ${change.direction === 'down' ? 'text-emerald-700' : 'text-rose-700'}`}>{changeText(change, money)}</p>
              )}
              {change?.direction === 'same' && <p className="mt-1 text-xs text-slate-500">{changeText(change, money)}</p>}
            </>
          ) : (
            <p className="text-sm text-slate-500">{t('card.noPriceYet')}</p>
          )}
        </div>
      </div>

      {!past && isUnavailable(watch) && (
        <p className="mt-3 rounded-xl bg-slate-50 px-3 py-2 text-sm text-slate-600">
          {unavailableText}
        </p>
      )}

      {Details && <Details watch={watch} />}

      <div className="mt-4">
        <Sparkline history={watch.history} target={target} format={money} />
        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
          {watch.lowest_price != null && (
            <span>{t('card.lowestSeen')} <strong className="font-semibold tabular-nums text-slate-700">{money(watch.lowest_price)}</strong></span>
          )}
          {watch.last_checked_at && <span>{t('card.checked', { when: agoLabel(watch.last_checked_at, now) })}</span>}
          {watch.status === 'active' && watch.next_check_at && <span>{t('card.nextCheck', { when: untilLabel(watch.next_check_at, now) })}</span>}
        </div>
      </div>

      {watch.status === 'error' && (
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-xl bg-amber-50 px-3 py-2 text-sm text-amber-900">
          <span>{watch.problem ? `${watch.problem} ` : ''}{t('card.errorPrice')}</span>
          <button type="button" data-tid="alerts.retry" onClick={() => onUpdate({ status: 'active' })} disabled={busy === 'status'}
            className="inline-flex items-center gap-1.5 rounded-full border border-amber-300 bg-white px-3 py-1 text-xs font-semibold hover:bg-amber-100">
            {busy === 'status' ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />} {t('ui.retry')}
          </button>
        </div>
      )}

      <p className="sr-only" aria-live="polite">{message?.text || ''}</p>
      {message && (
        <p className={`mt-3 text-sm ${message.tone === 'good' ? 'text-emerald-700' : message.tone === 'warn' ? 'text-amber-800' : 'text-slate-600'}`}>{message.text}</p>
      )}

      {onLiveCheck && (
        <LiveCheckPanel live={live} title={watch.title} buttonRef={liveButton}
          onDismissed={() => liveButton.current?.focus()} />
      )}

      {editing && (
        <EditPanel watch={watch} emailAvailable={emailAvailable} hasEmail={hasEmail}
          onCancel={() => setEditing(false)}
          onSave={async (changes) => { if (await onUpdate(changes)) setEditing(false) }} />
      )}

      <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-slate-100 pt-3">
        {!past && link && (
          <a href={link} data-tid="alerts.open-listing" target="_blank" rel="noopener noreferrer" onClick={onOpen} className={quiet}>
            <ExternalLink size={12} /> {openLabel}
          </a>
        )}
        <span className="ml-auto flex flex-wrap items-center gap-1">
          {!past && onLiveCheck && <LiveCheckButton live={live} buttonRef={liveButton} />}
          {!past && watch.status !== 'error' && (
            <button type="button" data-tid="alerts.check-now" onClick={onCheck} disabled={busy === 'check'} className={quiet}>
              {busy === 'check' ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
              {busy === 'check' ? t('ui.checking') : t('ui.checkNow')}
            </button>
          )}
          {watch.status === 'active' && (
            <button type="button" data-tid="alerts.pause" onClick={() => onUpdate({ status: 'paused' })} disabled={busy === 'status'} className={quiet}>
              <Pause size={12} /> {t('ui.pause')}
            </button>
          )}
          {watch.status === 'paused' && (
            <button type="button" data-tid="alerts.resume" onClick={() => onUpdate({ status: 'active' })} disabled={busy === 'status'} className={quiet}>
              <Play size={12} /> {t('ui.resume')}
            </button>
          )}
          {!past && !editing && (
            <button type="button" data-tid="alerts.edit" onClick={() => setEditing(true)} className={quiet}><Pencil size={12} /> {t('ui.edit')}</button>
          )}
          {!confirmDelete ? (
            <button type="button" data-tid="alerts.delete" onClick={() => setConfirmDelete(true)} className={quiet} aria-label={t('card.deleteAria', { name: watch.title })}>
              <Trash2 size={12} /> {t('ui.delete')}
            </button>
          ) : (
            <span className="inline-flex items-center gap-1 rounded-full bg-rose-50 py-0.5 pl-3 pr-1 text-xs text-rose-800" role="group" aria-label={t('card.confirmDelete')}>
              {t('card.stopWatching')}
              <button type="button" data-tid="alerts.delete-confirm" onClick={onDelete} disabled={busy === 'delete'} autoFocus
                className="rounded-full bg-rose-600 px-2.5 py-1 font-semibold text-white hover:bg-rose-700">
                {busy === 'delete' ? t('ui.deleting') : t('ui.delete')}
              </button>
              <button type="button" data-tid="alerts.delete-keep" onClick={() => setConfirmDelete(false)} className="rounded-full px-2 py-1 font-medium hover:bg-rose-100">{t('ui.keep')}</button>
            </span>
          )}
        </span>
      </div>
    </article>
  )
}
