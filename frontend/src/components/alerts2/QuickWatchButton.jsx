import { useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { createRoot } from 'react-dom/client'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { Eye, EyeOff, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useOptionalAuth } from '../../context/AuthContext'
import { useAlerts } from '../../context/AlertsContext'
import { useAlertsV2 } from '../../hooks/useAlertsV2'
import { quickWatch } from '../../services/alertsApi'
import { deleteFareWatch, deletePriceWatch } from '../../services/api'
import { priceWatchLink } from '../../utils/priceWatch'
import { loginPathFor } from '../../utils/returnPath'
import { emit } from '../../telemetry/client'
import i18n from '../../i18n'

const UNDO_MS = 5000
const BTN = 'inline-flex min-h-[44px] min-w-[44px] items-center justify-center gap-1.5 rounded-lg px-3 text-sm font-medium focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-600'
const IDLE = `${BTN} border border-teal-700 text-teal-800 hover:bg-teal-50 dark:text-teal-300 dark:hover:bg-slate-800`
const ON = `${BTN} bg-teal-700 text-white hover:bg-teal-800`

const track = (kind, action, surface) => { try { emit('alert_quick_watch', { kind, action, surface }) } catch { /* never break the UI */ } }
const removeWatch = (kind, id, token) => (kind === 'flight' ? deleteFareWatch(id, token) : deletePriceWatch(id, token))
const KNOWN_ERRORS = ['watch_limit', 'live_prices_off', 'spec_invalid']


// The Undo toast lives outside the button: a module-level store rendered by its
// own tiny React root on document.body, so it survives the card unmounting
// (e.g. a re-render of the results list) inside the 5 s window.
let toastState = null // {kind, id, token, surface, error, onUndone}
let toastTimer = null
let toastRoot = null
let toastHost = null
const listeners = new Set()
const emitToast = () => listeners.forEach((l) => l())
const setToastState = (next) => { toastState = next; emitToast() }
const clearToast = () => { clearTimeout(toastTimer); setToastState(null) }
const armToast = () => { clearTimeout(toastTimer); toastTimer = setTimeout(clearToast, UNDO_MS) }

function showUndoToast(entry) {
  setToastState({ ...entry, error: false })
  armToast()
  if (!toastRoot && typeof document !== 'undefined') {
    toastHost = document.createElement('div')
    toastHost.setAttribute('data-tid', 'quick-watch-toast-host')
    document.body.appendChild(toastHost)
    toastRoot = createRoot(toastHost)
    toastRoot.render(<UndoToast />)
  }
}

async function undoToast() {
  const cur = toastState
  if (!cur) return
  clearTimeout(toastTimer)
  try {
    await removeWatch(cur.kind, cur.id, cur.token)
    track(cur.kind, 'undo', cur.surface)
    setToastState(null)
    cur.onUndone?.()
  } catch {
    setToastState({ ...cur, error: true })
    armToast()
  }
}

/** Test hook: drop any toast and its host. */
export function _resetQuickWatchToast() {
  clearToast()
  if (toastRoot) { toastRoot.unmount(); toastHost.remove(); toastRoot = null; toastHost = null }
}

function UndoToast() {
  const cur = useSyncExternalStore((l) => { listeners.add(l); return () => listeners.delete(l) }, () => toastState)
  if (!cur) return null
  const t = (k) => i18n.t(`quickWatch:${k}`)
  return (
    <div role="status" aria-live="polite" data-tid="quick-watch-toast"
      className="alert-pop fixed inset-x-4 bottom-4 z-[70] flex items-center gap-3 rounded-2xl border border-slate-200 bg-white p-3 shadow-xl sm:inset-x-auto sm:right-6 sm:bottom-6 sm:max-w-sm dark:border-slate-700 dark:bg-slate-900">
      <p className="min-w-0 flex-1 text-sm text-slate-900 dark:text-slate-100">
        {cur.error ? t('toast.undoFailed') : t('toast.message')}
      </p>
      {!cur.error && (
        <button type="button" data-tid="quick-watch-undo" onClick={undoToast}
          className="inline-flex min-h-[44px] items-center rounded-lg px-3 text-sm font-semibold text-teal-800 hover:bg-teal-50 dark:text-teal-300 dark:hover:bg-slate-800">
          {t('toast.undo')}
        </button>
      )}
      <button type="button" data-tid="quick-watch-dismiss" onClick={clearToast} aria-label={t('toast.dismiss')}
        className="inline-flex h-11 w-11 items-center justify-center rounded-full text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800">
        <X size={16} aria-hidden="true" />
      </button>
    </div>
  )
}

/**
 * One-tap "Watch price" on a card. Optimistic: it reads "Watching" at once
 * (with a small bounce) and rolls back if the request fails. A toast offers
 * Undo for 5 s (it outlives this button). Hidden unless the server can make
 * live looks; signed out, a tap leads to sign-in.
 */
export default function QuickWatchButton({ kind, title, subtitle, spec, planId, surface = 'results' }) {
  const { t } = useTranslation('quickWatch')
  const { token } = useOptionalAuth()
  const { livePrices } = useAlertsV2()
  const { watchesChanged } = useAlerts()
  const navigate = useNavigate()
  const location = useLocation()
  const [state, setState] = useState('idle') // idle | on | existing
  const [watch, setWatch] = useState(null)
  const [error, setError] = useState(null)
  const busy = useRef(false)
  const mounted = useRef(true)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  const safe = (fn) => { if (mounted.current) fn() }

  if (!livePrices) return null

  const add = async () => {
    if (busy.current) return
    busy.current = true
    setError(null)
    setState('on')
    try {
      const body = { kind, title, spec, surface, ...(subtitle ? { subtitle } : {}), ...(planId != null ? { plan_id: planId } : {}) }
      const res = await quickWatch(token, body)
      safe(() => setWatch(res.watch))
      watchesChanged?.()
      if (res.existing) {
        safe(() => setState('existing'))
        track(kind, 'exists', surface)
      } else {
        track(kind, 'add', surface)
        showUndoToast({
          kind, id: res.watch.id, token, surface,
          onUndone: () => { safe(() => { setState('idle'); setWatch(null) }); watchesChanged?.() },
        })
      }
    } catch (err) {
      safe(() => {
        setState('idle')
        setError(KNOWN_ERRORS.includes(err?.code) ? err.code : 'generic')
      })
      if (err?.status === 409) track(kind, 'blocked', surface)
    } finally {
      busy.current = false
    }
  }

  const onClick = () => {
    if (!token) { navigate(loginPathFor(location)); return }
    if (state === 'idle') add()
  }

  return (
    <>
      {state === 'existing' && watch ? (
        <Link to={priceWatchLink({ kind, id: watch.id })} data-tid="quick-watch-existing" className={ON}
          aria-label={t('aria.already', { title })}>
          <Eye size={16} aria-hidden="true" /> {t('label.already')}
        </Link>
      ) : (
        <button type="button" data-tid="quick-watch" aria-pressed={state === 'on'} onClick={onClick}
          aria-label={t('aria.watch', { title })} className={state === 'on' ? ON : IDLE}>
          {state === 'on'
            ? <Eye size={16} aria-hidden="true" className="bell-nudge" />
            : <EyeOff size={16} aria-hidden="true" />}
          <span>{state === 'on' ? t('label.watching') : t('label.watch')}</span>
        </button>
      )}
      {error && <p role="alert" data-tid="quick-watch-error" className="mt-1 text-xs text-red-700 dark:text-red-400">{t(`error.${error}`)}</p>}
    </>
  )
}
