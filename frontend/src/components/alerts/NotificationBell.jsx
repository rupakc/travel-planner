import { useEffect, useId, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Bell, Loader2 } from 'lucide-react'
import { useAuth } from '../../context/AuthContext'
import { useAlerts } from '../../context/AlertsContext'
import { listNotifications } from '../../services/api'
import { notificationLink, relativeTime } from '../../utils/fareWatch'
import { track } from '../../utils/analytics'
import { kindOf, keepDeltaTogether } from './alertKinds'

export function NotificationItem({ n, onOpen, now = new Date() }) {
  const { Icon, tone, action } = kindOf(n.kind)
  const unread = !n.read_at
  return (
    <li>
      <button type="button" onClick={() => onOpen(n)}
        className="flex w-full gap-3 px-4 py-3 text-left hover:bg-slate-50 focus-visible:bg-slate-50 focus-visible:outline-none">
        <span className={`mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full ${tone}`}>
          <Icon size={15} aria-hidden="true" />
        </span>
        <span className="min-w-0 flex-1">
          <span className={`block text-sm leading-snug ${unread ? 'font-semibold text-slate-900' : 'text-slate-700'}`}>{keepDeltaTogether(n.title)}</span>
          <span className="mt-0.5 line-clamp-2 block text-xs text-slate-500">{n.body}</span>
          <span className="mt-1 flex items-center gap-2 text-[11px]">
            <span className="text-slate-400">{relativeTime(n.created_at, now)}</span>
            <span className="font-medium text-sky-700">{action}</span>
          </span>
        </span>
        {unread && <span className="mt-2 h-2 w-2 shrink-0 rounded-full bg-sky-500" aria-label="Unread" />}
      </button>
    </li>
  )
}

/** Header bell: unread badge, and a panel with the latest 10 notifications. */
export default function NotificationBell() {
  const { token } = useAuth()
  const { unread, markRead } = useAlerts()
  const navigate = useNavigate()
  const panelId = useId()
  const [open, setOpen] = useState(false)
  const [items, setItems] = useState(null)
  const [failed, setFailed] = useState(false)
  const [nudge, setNudge] = useState(false)
  const [announcement, setAnnouncement] = useState('')
  const prev = useRef(unread)
  const wrapRef = useRef(null)
  const buttonRef = useRef(null)

  // One nudge + one screen-reader announcement when new alerts arrive
  useEffect(() => {
    if (unread > prev.current) {
      setNudge(true)
      setAnnouncement(`${unread} unread fare alert${unread === 1 ? '' : 's'}`)
    }
    prev.current = unread
  }, [unread])

  useEffect(() => {
    if (!open) return undefined
    let active = true
    setFailed(false)
    listNotifications(token, { limit: 10 })
      .then(page => { if (active) setItems(page.items) })
      .catch(() => { if (active) setFailed(true) })
    const onDoc = (e) => { if (!wrapRef.current?.contains(e.target)) setOpen(false) }
    const onKey = (e) => {
      if (e.key === 'Escape') { setOpen(false); buttonRef.current?.focus() }
    }
    document.addEventListener('mousedown', onDoc)
    document.addEventListener('keydown', onKey)
    return () => {
      active = false
      document.removeEventListener('mousedown', onDoc)
      document.removeEventListener('keydown', onKey)
    }
  }, [open, token])

  const openItem = (n) => {
    track('alert_clicked', 'bell', { kind: n.kind })
    if (!n.read_at) markRead([n.id])
    setOpen(false)
    navigate(notificationLink(n))
  }

  const markAll = async () => {
    await markRead('all')
    setItems(list => list?.map(n => ({ ...n, read_at: n.read_at || new Date().toISOString() })))
  }

  const badge = unread > 9 ? '9+' : String(unread)
  return (
    <div ref={wrapRef} className="relative">
      <button ref={buttonRef} type="button" onClick={() => setOpen(o => !o)}
        aria-expanded={open} aria-controls={panelId}
        aria-label={unread ? `Notifications, ${unread} unread` : 'Notifications'}
        className="relative flex h-9 w-9 items-center justify-center rounded-full text-slate-500 hover:bg-slate-100 hover:text-slate-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-500">
        <Bell size={17} className={nudge ? 'bell-nudge' : ''} onAnimationEnd={() => setNudge(false)} />
        {unread > 0 && (
          <span aria-hidden="true"
            className="absolute right-0.5 top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-sky-600 px-1 text-[10px] font-bold leading-none text-white tabular-nums ring-2 ring-white">
            {badge}
          </span>
        )}
      </button>
      <span className="sr-only" aria-live="polite">{announcement}</span>

      {open && (
        <div id={panelId} role="region" aria-label="Notifications"
          className="alert-pop fixed inset-x-4 top-16 z-[55] overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-xl sm:absolute sm:inset-x-auto sm:right-0 sm:top-11 sm:w-[22rem]">
          <div className="flex items-center justify-between border-b border-slate-100 px-4 py-2.5">
            <h2 className="text-sm font-semibold text-slate-800">Fare alerts</h2>
            <button type="button" onClick={markAll} disabled={!unread}
              className="text-xs font-medium text-sky-700 hover:text-sky-900 disabled:cursor-default disabled:text-slate-300">
              Mark all as read
            </button>
          </div>
          <div className="max-h-[60vh] overflow-y-auto">
            {items === null && !failed && (
              <p className="flex items-center gap-2 px-4 py-6 text-sm text-slate-500"><Loader2 size={14} className="animate-spin" /> Loading…</p>
            )}
            {failed && <p className="px-4 py-6 text-sm text-slate-500">Couldn’t load alerts. Check your connection and open this again.</p>}
            {items?.length === 0 && (
              <div className="px-4 py-6 text-sm text-slate-500">
                <p className="font-medium text-slate-700">No alerts yet</p>
                <p className="mt-1">Watch a fare from your flight results and we’ll tell you here when it drops.</p>
              </div>
            )}
            {items?.length > 0 && (
              <ul className="divide-y divide-slate-100">
                {items.map(n => <NotificationItem key={n.id} n={n} onOpen={openItem} />)}
              </ul>
            )}
          </div>
          <Link to="/alerts" onClick={() => setOpen(false)}
            className="block border-t border-slate-100 px-4 py-2.5 text-center text-sm font-medium text-sky-700 hover:bg-slate-50">
            See all watched fares
          </Link>
        </div>
      )}
    </div>
  )
}
