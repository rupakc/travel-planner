import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { X } from 'lucide-react'
import { useAlerts } from '../../context/AlertsContext'
import { notificationLink } from '../../utils/fareWatch'
import { track } from '../../utils/analytics'
import { alertKindFor, keepDeltaTogether } from './alertKinds'

const VISIBLE_MS = 10000

/** One toast at a time for an alert that arrives while the app is open.
 * Dismissible, pauses while hovered or focused, then quietly leaves. */
export default function AlertToast() {
  const { toast, dismissToast, markRead } = useAlerts()
  const navigate = useNavigate()
  const [paused, setPaused] = useState(false)
  const timer = useRef(null)

  useEffect(() => {
    if (!toast || paused) return undefined
    timer.current = setTimeout(dismissToast, VISIBLE_MS)
    return () => clearTimeout(timer.current)
  }, [toast, paused, dismissToast])

  const { Icon, tone, action } = alertKindFor(toast)
  const open = () => {
    track('alert_clicked', 'toast', { kind: toast.kind })
    markRead([toast.id])
    navigate(notificationLink(toast))
    dismissToast()
  }

  return (
    <div aria-live="polite" role="status"
      className="pointer-events-none fixed inset-x-4 bottom-4 z-[70] flex justify-end sm:inset-x-auto sm:right-6 sm:bottom-6">
      {toast && (
        <div key={toast.id} onMouseEnter={() => setPaused(true)} onMouseLeave={() => setPaused(false)}
          onFocus={() => setPaused(true)} onBlur={() => setPaused(false)}
          className="alert-pop pointer-events-auto flex w-full max-w-sm gap-3 rounded-2xl border border-slate-200 bg-white p-4 shadow-xl">
          <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full ${tone}`}>
            <Icon size={16} aria-hidden="true" />
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold leading-snug text-slate-900">{keepDeltaTogether(toast.title)}</p>
            <p className="mt-0.5 line-clamp-2 text-xs text-slate-500">{toast.body}</p>
            <button type="button" onClick={open}
              className="mt-2 text-xs font-semibold text-sky-700 hover:text-sky-900">{action}</button>
          </div>
          <button type="button" onClick={dismissToast} aria-label="Dismiss alert"
            className="-mr-1 -mt-1 h-7 w-7 shrink-0 rounded-full text-slate-400 hover:bg-slate-100 hover:text-slate-600 flex items-center justify-center">
            <X size={15} />
          </button>
        </div>
      )}
    </div>
  )
}
