import { useEffect, useId, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useOptionalAuth } from '../../context/AuthContext'
import { useAlerts } from '../../context/AlertsContext'
import { useAlertsV2 } from '../../hooks/useAlertsV2'
import { getSuggestions, quickWatch } from '../../services/alertsApi'
import { emit } from '../../telemetry/client'

const track = (action, count) => { try { emit('alert_suggest', { action, count }) } catch { /* never break the UI */ } }
const seenKey = (userId, planId) => `tp_suggest_seen:${userId}:${planId}`
const wasSeen = (k) => { try { return window.localStorage.getItem(k) !== null } catch { return false } }
const markSeen = (k) => { try { window.localStorage.setItem(k, '1') } catch { /* private mode */ } }
const KNOWN_ERRORS = ['watch_limit', 'live_prices_off', 'spec_invalid']
const REASONS = ['selected_in_plan', 'trip_total', 'departure_soon']
const BTN = 'inline-flex min-h-[44px] min-w-[44px] items-center justify-center rounded-lg px-4 text-sm font-medium focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-600'
const PRIMARY = `${BTN} bg-teal-700 text-white hover:bg-teal-800 disabled:opacity-60`
const SECONDARY = `${BTN} border border-slate-300 text-slate-700 hover:bg-slate-50`
const FOCUSABLE = 'button:not([disabled]), input:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])'

const rowKey = (s, i) => `${s.kind}:${i}`

/**
 * Bottom sheet (a dialog on desktop) offered once after a plan is saved:
 * "Want us to watch these prices?". Everything but the trip total is pre-ticked;
 * already-watched rows are disabled. "Watch N" creates the ticked watches one
 * after the other, with per-row progress and a Retry on a failed row. Never
 * shown without live prices, with no suggestions, or twice for one plan and
 * user. Props: planId (the saved plan), onDone (optional; also accepted as onClose), force (skip the once-per-plan guard, for the manual button).
 */
export default function WatchSuggestions({ planId, onDone, onClose, force = false }) {
  const { t } = useTranslation('watchSuggest')
  const { token, user } = useOptionalAuth()
  const { livePrices } = useAlertsV2()
  const { watchesChanged } = useAlerts()
  const [items, setItems] = useState(null) // null = closed
  const [ticked, setTicked] = useState({})
  const [status, setStatus] = useState({}) // key -> 'running' | 'done' | 'failed'
  const [errors, setErrors] = useState({}) // key -> error code
  const [running, setRunning] = useState(false)
  const titleId = useId()
  const dialogRef = useRef(null)
  const mounted = useRef(true)
  const finished = useRef(false) // accepted: no "dismissed" on close
  const userId = user?.id

  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])

  useEffect(() => {
    if (!livePrices || !token || userId == null || planId == null) return undefined
    const key = seenKey(userId, planId)
    if (!force && wasSeen(key)) return undefined
    let cancelled = false
    getSuggestions(token, planId).then((res) => {
      if (cancelled || res?.live_prices === false) return
      const list = Array.isArray(res?.suggestions) ? res.suggestions : []
      if (!list.length || (!force && wasSeen(key))) return
      markSeen(key)
      finished.current = false
      setStatus({}); setErrors({})
      setItems(list)
      setTicked(Object.fromEntries(list.map((s, i) => [rowKey(s, i), s.kind !== 'trip' && !s.already_watching])))
      track('shown', list.length)
    }).catch(() => { /* a hint only: stay quiet */ })
    return () => { cancelled = true }
  }, [livePrices, token, userId, planId, force])

  const close = () => {
    if (items && !finished.current) track('dismissed', items.length)
    setItems(null)
    ;(onDone ?? onClose)?.()
  }

  const closeRef = useRef(close)
  closeRef.current = close
  useEffect(() => {
    if (!items) return undefined
    const opener = document.activeElement
    dialogRef.current?.querySelector('input:not([disabled]),button')?.focus()
    const onKey = (e) => {
      if (e.key === 'Escape') { closeRef.current(); return }
      if (e.key !== 'Tab' || !dialogRef.current) return
      const els = [...dialogRef.current.querySelectorAll(FOCUSABLE)]
      if (!els.length) return
      const first = els[0]; const last = els[els.length - 1]
      const inside = dialogRef.current.contains(document.activeElement)
      if (e.shiftKey && (document.activeElement === first || !inside)) { e.preventDefault(); last.focus() }
      else if (!e.shiftKey && (document.activeElement === last || !inside)) { e.preventDefault(); first.focus() }
    }
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('keydown', onKey)
      if (opener && typeof opener.focus === 'function') opener.focus()
    }
  }, [items !== null])

  if (!items) return null

  const safe = (fn) => { if (mounted.current) fn() }
  const pending = items.map((s, i) => ({ s, k: rowKey(s, i) }))
    .filter(({ s, k }) => ticked[k] && !s.already_watching && status[k] !== 'done')

  const createOne = async ({ s, k }) => {
    safe(() => { setStatus((p) => ({ ...p, [k]: 'running' })); setErrors((p) => ({ ...p, [k]: null })) })
    try {
      await quickWatch(token, {
        kind: s.kind, title: s.title, spec: s.spec, surface: 'suggest', plan_id: planId,
        ...(s.subtitle ? { subtitle: s.subtitle } : {}),
      })
      safe(() => setStatus((p) => ({ ...p, [k]: 'done' })))
      return true
    } catch (err) {
      safe(() => {
        setStatus((p) => ({ ...p, [k]: 'failed' }))
        setErrors((p) => ({ ...p, [k]: KNOWN_ERRORS.includes(err?.code) ? err.code : 'generic' }))
      })
      return false
    }
  }

  const run = async (list, first) => {
    if (running || !list.length) return
    if (first && !finished.current) { finished.current = true; track('accepted', list.length) }
    setRunning(true)
    let created = 0
    for (const row of list) { if (await createOne(row)) created += 1 }
    if (created) watchesChanged?.()
    safe(() => setRunning(false))
  }

  const doneCount = items.filter((s, i) => status[rowKey(s, i)] === 'done').length
  const allDone = pending.length === 0 && doneCount > 0 && !running

  return createPortal(
    <div className="fixed inset-0 z-[60] flex items-end justify-center sm:items-center sm:p-4" data-tid="watch-suggest">
      <div className="absolute inset-0 bg-slate-900/40" onClick={close} aria-hidden="true" />
      <div ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby={titleId}
        className="relative max-h-[92vh] w-full overflow-y-auto rounded-t-2xl bg-white p-5 shadow-xl sm:max-w-md sm:rounded-2xl">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 id={titleId} className="text-base font-semibold text-slate-900">{t('title')}</h2>
            <p className="mt-0.5 text-sm text-slate-600">{t('subtitle')}</p>
          </div>
          <button type="button" data-tid="watch-suggest-close" onClick={close} aria-label={t('close')}
            className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-full text-slate-500 hover:bg-slate-100">
            <X size={18} aria-hidden="true" />
          </button>
        </div>
        <ul className="mt-3 space-y-2">
          {items.map((s, i) => {
            const k = rowKey(s, i)
            const st = status[k]
            const locked = s.already_watching || st === 'done' || running
            return (
              <li key={k} data-tid="watch-suggest-row" className="rounded-xl border border-slate-200">
                <label className={`flex min-h-[44px] items-start gap-3 p-3 ${locked ? 'opacity-80' : 'cursor-pointer'}`}>
                  <input type="checkbox" data-tid="watch-suggest-toggle" className="mt-1 h-5 w-5 accent-teal-700"
                    checked={s.already_watching || st === 'done' || !!ticked[k]} disabled={locked}
                    onChange={(e) => setTicked((p) => ({ ...p, [k]: e.target.checked }))} />
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm font-medium text-slate-900">{s.title}</span>
                    {s.subtitle && <span className="block text-xs text-slate-600">{s.subtitle}</span>}
                    <span className="block text-xs text-slate-500">
                      {REASONS.includes(s.reason) ? t(`reason.${s.reason}`) : ''}
                    </span>
                  </span>
                </label>
                <div className={`flex items-center justify-between gap-2 px-3 text-xs ${s.already_watching || st ? 'pb-3' : ''}`} data-tid="watch-suggest-status" aria-live="polite">
                  {(s.already_watching || st) && (
                    <>
                    {s.already_watching && <span className="text-slate-600">{t('status.already')}</span>}
                    {!s.already_watching && st === 'running' && <span className="text-slate-600">{t('status.running')}</span>}
                    {!s.already_watching && st === 'done' && <span className="font-medium text-teal-800">{t('status.done')}</span>}
                    {!s.already_watching && st === 'failed' && (
                      <>
                        <span role="alert" className="text-red-700">{t(`error.${errors[k] || 'generic'}`)}</span>
                        <button type="button" data-tid="watch-suggest-retry" disabled={running}
                          onClick={() => run([{ s, k }], false)}
                          className="inline-flex min-h-[44px] min-w-[44px] items-center justify-center rounded-lg px-3 text-sm font-semibold text-teal-800 hover:bg-teal-50">
                          {t('retry')}
                        </button>
                      </>
                    )}
                    </>
                  )}
                </div>
              </li>
            )
          })}
        </ul>
        <div className="mt-4 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          {allDone ? (
            <button type="button" data-tid="watch-suggest-done" onClick={close} className={PRIMARY}>{t('done')}</button>
          ) : (
            <>
              <button type="button" data-tid="watch-suggest-dismiss" onClick={close} className={SECONDARY}>{t('notNow')}</button>
              <button type="button" data-tid="watch-suggest-accept" disabled={running || pending.length === 0}
                onClick={() => run(pending, true)} className={PRIMARY}>
                {t('watchN', { count: pending.length })}
              </button>
            </>
          )}
        </div>
      </div>
    </div>,
    document.body,
  )
}
