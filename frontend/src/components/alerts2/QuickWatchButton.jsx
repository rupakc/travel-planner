import { useEffect, useRef, useState } from 'react'
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

const UNDO_MS = 5000
const BTN = 'inline-flex min-h-[44px] min-w-[44px] items-center justify-center gap-1.5 rounded-lg px-3 text-sm font-medium focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-600'
const IDLE = `${BTN} border border-teal-700 text-teal-800 hover:bg-teal-50 dark:text-teal-300 dark:hover:bg-slate-800`
const ON = `${BTN} bg-teal-700 text-white hover:bg-teal-800`

const track = (kind, action, surface) => { try { emit('alert_quick_watch', { kind, action, surface }) } catch { /* never break the UI */ } }
const removeWatch = (kind, id, token) => (kind === 'flight' ? deleteFareWatch(id, token) : deletePriceWatch(id, token))
const KNOWN_ERRORS = ['watch_limit', 'live_prices_off', 'spec_invalid']

/**
 * One-tap "Watch price" on a card. Optimistic: it reads "Watching" at once
 * (with a small bounce) and rolls back if the request fails. A toast offers
 * Undo for 5 s. Hidden unless the server can make live looks; signed out, a
 * tap leads to sign-in. The toast is local: AlertsContext's toast is for
 * incoming notifications and has no action slot.
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
  const [toast, setToast] = useState(false)
  const busy = useRef(false)
  const timer = useRef(null)
  useEffect(() => () => clearTimeout(timer.current), [])

  if (!livePrices) return null

  const closeToast = () => { clearTimeout(timer.current); setToast(false) }

  const undo = async () => {
    if (busy.current || !watch) return
    busy.current = true
    closeToast()
    const prev = state
    setState('idle')
    try {
      await removeWatch(kind, watch.id, token)
      track(kind, 'undo', surface)
      setWatch(null)
      watchesChanged?.()
    } catch {
      setState(prev)
    } finally {
      busy.current = false
    }
  }

  const add = async () => {
    if (busy.current) return
    busy.current = true
    setError(null)
    setState('on')
    try {
      const body = { kind, title, spec, surface, ...(subtitle ? { subtitle } : {}), ...(planId != null ? { plan_id: planId } : {}) }
      const res = await quickWatch(token, body)
      setWatch(res.watch)
      watchesChanged?.()
      if (res.existing) {
        setState('existing')
        track(kind, 'exists', surface)
      } else {
        track(kind, 'add', surface)
        setToast(true)
        clearTimeout(timer.current)
        timer.current = setTimeout(() => setToast(false), UNDO_MS)
      }
    } catch (err) {
      setState('idle')
      const code = KNOWN_ERRORS.includes(err?.code) ? err.code : 'generic'
      setError(code)
      if (err?.status === 409) track(kind, 'blocked', surface)
    } finally {
      busy.current = false
    }
  }

  const onClick = () => {
    if (!token) { navigate(loginPathFor(location)); return }
    if (state === 'on') undo()
    else add()
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
          aria-label={state === 'on' ? t('aria.unwatch', { title }) : t('aria.watch', { title })}
          className={state === 'on' ? ON : IDLE}>
          {state === 'on'
            ? <Eye size={16} aria-hidden="true" className="bell-nudge" />
            : <EyeOff size={16} aria-hidden="true" />}
          <span>{state === 'on' ? t('label.watching') : t('label.watch')}</span>
        </button>
      )}
      {error && <p role="alert" data-tid="quick-watch-error" className="mt-1 text-xs text-red-700 dark:text-red-400">{t(`error.${error}`)}</p>}
      {toast && (
        <div role="status" aria-live="polite" data-tid="quick-watch-toast"
          className="alert-pop fixed inset-x-4 bottom-4 z-[70] flex items-center gap-3 rounded-2xl border border-slate-200 bg-white p-3 shadow-xl sm:inset-x-auto sm:right-6 sm:bottom-6 sm:max-w-sm dark:border-slate-700 dark:bg-slate-900">
          <p className="min-w-0 flex-1 text-sm text-slate-900 dark:text-slate-100">{t('toast.message')}</p>
          <button type="button" data-tid="quick-watch-undo" onClick={undo}
            className="inline-flex min-h-[44px] items-center rounded-lg px-3 text-sm font-semibold text-teal-800 hover:bg-teal-50 dark:text-teal-300 dark:hover:bg-slate-800">
            {t('toast.undo')}
          </button>
          <button type="button" data-tid="quick-watch-dismiss" onClick={closeToast} aria-label={t('toast.dismiss')}
            className="inline-flex h-11 w-11 items-center justify-center rounded-full text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800">
            <X size={16} aria-hidden="true" />
          </button>
        </div>
      )}
    </>
  )
}
