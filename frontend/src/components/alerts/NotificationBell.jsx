import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Bell, Loader2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../../context/AuthContext'
import { useAlerts } from '../../context/AlertsContext'
import { useAlertsV2 } from '../../hooks/useAlertsV2'
import { groupDrops } from '../../utils/notificationGroups'
import { listNotifications } from '../../services/api'
import { notificationLink } from '../../utils/fareWatch'
import { track } from '../../utils/analytics'
import i18n from '../../i18n'
import { actionText, alertKindFor, keepDeltaTogether } from './alertKinds'
import { relativeTime as agoLabel } from '../../utils/fareWatch'

const GROUP_WINDOW_MIN = 15   // the default push-grouping window

export function NotificationItem({ n, onOpen, now = new Date() }) {
  const { t } = useTranslation('alerts')
  const { Icon, tone, action } = alertKindFor(n)
  const unread = !n.read_at
  return (
    <li>
      <button type="button" data-tid="alerts.notification-item" onClick={() => onOpen(n)}
        className="flex w-full gap-3 px-4 py-3 text-left hover:bg-slate-50 focus-visible:bg-slate-50 focus-visible:outline-none">
        <span className={`mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full ${tone}`}>
          <Icon size={15} aria-hidden="true" />
        </span>
        <span className="min-w-0 flex-1">
          <span className={`block text-sm leading-snug ${unread ? 'font-semibold text-slate-900' : 'text-slate-700'}`}>{keepDeltaTogether(n.title)}</span>
          <span className="mt-0.5 line-clamp-2 block text-xs text-slate-500">{n.body}</span>
          {String(n.kind || '').startsWith('weather_') && (
            <span className="mt-0.5 block text-[10px] text-slate-400" data-tid="alerts.weather-credit">{t('bell.weatherCredit')}</span>
          )}
          <span className="mt-1 flex items-center gap-2 text-[11px]">
            <span className="text-slate-400">{agoLabel(n.created_at, now)}</span>
            <span className="font-medium text-sky-700">{actionText(action)}</span>
          </span>
        </span>
        {unread && <span className="mt-2 h-2 w-2 shrink-0 rounded-full bg-sky-500" aria-label={t('bell.unreadBadge')} />}
      </button>
    </li>
  )
}

/** Header bell: unread badge, and a panel with the latest 10 notifications. */
export default function NotificationBell() {
  const { t } = useTranslation('alerts')
  const { token } = useAuth()
  const { unread, markRead } = useAlerts()
  const navigate = useNavigate()
  const { on: v2 } = useAlertsV2()
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
      setAnnouncement(i18n.t('alerts:bell.announce', { count: unread }))
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

  // v2: drops that arrived together read as one row ("3 price drops")
  const rows = useMemo(() => {
    if (!items) return []
    if (!v2) return items.map(n => ({ n, ids: [n.id], count: 1 }))
    return groupDrops(items, GROUP_WINDOW_MIN).map(g => ({ n: g.latest, ids: g.ids, count: g.count }))
  }, [items, v2])

  const openItem = (n, ids = [n.id]) => {
    track('alert_clicked', 'bell', { kind: n.kind })
    const unreadIds = (items || []).filter(x => ids.includes(x.id) && !x.read_at).map(x => x.id)
    if (unreadIds.length) markRead(unreadIds)
    setOpen(false)
    navigate(v2 && n.kind === 'price_digest' ? '/alerts?from=digest&via=in_app' : notificationLink(n))
  }

  const markAll = async () => {
    await markRead('all')
    setItems(list => list?.map(n => ({ ...n, read_at: n.read_at || new Date().toISOString() })))
  }

  const badge = unread > 9 ? '9+' : String(unread)
  return (
    <div ref={wrapRef} className="relative">
      <button ref={buttonRef} type="button" data-tid="alerts.bell" onClick={() => setOpen(o => !o)}
        aria-expanded={open} aria-controls={panelId}
        aria-label={unread ? t('bell.notificationsUnread', { n: unread }) : t('bell.notifications')}
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
        <div id={panelId} role="region" aria-label={t('bell.notifications')}
          className="alert-pop fixed inset-x-4 top-16 z-[55] overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-xl sm:absolute sm:inset-x-auto sm:right-0 sm:top-11 sm:w-[22rem]">
          <div className="flex items-center justify-between border-b border-slate-100 px-4 py-2.5">
            <h2 className="text-sm font-semibold text-slate-800">{t('bell.title')}</h2>
            <button type="button" data-tid="alerts.mark-all-read" onClick={markAll} disabled={!unread}
              className="text-xs font-medium text-sky-700 hover:text-sky-900 disabled:cursor-default disabled:text-slate-300">
              {t('bell.markAll')}
            </button>
          </div>
          <div className="max-h-[60vh] overflow-y-auto">
            {items === null && !failed && (
              <p className="flex items-center gap-2 px-4 py-6 text-sm text-slate-500"><Loader2 size={14} className="animate-spin" /> {t('bell.loading')}</p>
            )}
            {failed && <p className="px-4 py-6 text-sm text-slate-500">{t('bell.loadFailed')}</p>}
            {items?.length === 0 && (
              <div className="px-4 py-6 text-sm text-slate-500">
                <p className="font-medium text-slate-700">{t('bell.emptyTitle')}</p>
                <p className="mt-1">{t('bell.emptyBody')}</p>
              </div>
            )}
            {items?.length > 0 && (
              <ul className="divide-y divide-slate-100">
                {rows.map(({ n, ids, count }) => count > 1
                  ? <NotificationItem key={ids.join('-')} onOpen={() => openItem(n, ids)}
                    n={{ ...n, title: t('bell.groupTitle', { count }), body: t('bell.groupLatest', { title: n.title }), read_at: ids.every(id => items.find(x => x.id === id)?.read_at) ? n.read_at : null }} />
                  : <NotificationItem key={n.id} n={n} onOpen={() => openItem(n)} />)}
              </ul>
            )}
          </div>
          <Link to="/alerts" data-tid="alerts.see-all" onClick={() => setOpen(false)}
            className="block border-t border-slate-100 px-4 py-2.5 text-center text-sm font-medium text-sky-700 hover:bg-slate-50">
            {t('bell.seeAll')}
          </Link>
        </div>
      )}
    </div>
  )
}
