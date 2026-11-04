import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { useAuth } from './AuthContext'
import {
  getCapabilities, getUnreadCount, listNotifications, markNotificationsRead, matchFareWatch,
} from '../services/api'
import { newestUnseen, tripKey } from '../utils/fareWatch'

/**
 * Fare alerts state shared by the bell, the toast, the Alerts page and every
 * "Watch this fare" button.
 *
 * - Polls the unread count every `pollMs` while the tab is visible; stops
 *   while hidden and refreshes on return / focus.
 * - A newly arrived notification shows as one toast (replacing any older
 *   one) — or, when the window isn't focused and the traveller allowed it,
 *   as a native browser notification.
 */
// Outside the provider (isolated component tests, public pages) alerts are
// simply unavailable: watch buttons render nothing, counts stay zero.
const INERT = {
  unread: 0, refresh: async () => {}, markRead: async () => {}, markSeen: () => {}, toast: null,
  showToast: () => {}, dismissToast: () => {},
  caps: { serpapi: false, fareWatch: false, email: false },
  watchFor: async () => null, watchVersion: 0, watchesChanged: () => {},
  permission: 'unsupported', shouldOfferBrowserAlerts: () => false, answerBrowserAlerts: async () => {},
}
const AlertsContext = createContext(INERT)

const PROMPTED_KEY = 'tp_alert_permission_asked'

const browserPermission = () =>
  (typeof window !== 'undefined' && 'Notification' in window ? window.Notification.permission : 'unsupported')

function safeStorage(fn, fallback = null) {
  try { return fn() } catch { return fallback }
}

export function AlertsProvider({ children, pollMs = 60000, onOpenLink = null }) {
  const { token } = useAuth()
  const [unread, setUnread] = useState(0)
  const [toast, setToast] = useState(null)
  const [caps, setCaps] = useState({ serpapi: false, fareWatch: false, email: false })
  const [permission, setPermission] = useState(browserPermission)
  const [watchVersion, setWatchVersion] = useState(0)
  const seenId = useRef(null)      // newest notification id already known; null before first load
  const lastCount = useRef(0)
  const matches = useRef(new Map())
  const openLink = useRef(onOpenLink)
  useEffect(() => { openLink.current = onOpenLink }, [onOpenLink])

  useEffect(() => {
    let active = true
    getCapabilities().then(c => { if (active) setCaps(c) })
    return () => { active = false }
  }, [])

  const announce = useCallback((n) => {
    const focused = typeof document.hasFocus === 'function' ? document.hasFocus() : true
    if (!focused && browserPermission() === 'granted') {
      try {
        const native = new window.Notification(n.title, { body: n.body, tag: `fare-alert-${n.id}` })
        native.onclick = () => { window.focus(); openLink.current?.(n); native.close() }
        return
      } catch { /* fall back to the toast */ }
    }
    setToast(n)
  }, [])

  // One refresh at a time: focus and visibilitychange fire together on return
  const inflight = useRef(null)

  const doRefresh = useCallback(async () => {
    try {
      const count = await getUnreadCount(token)
      const grew = count > lastCount.current
      lastCount.current = count
      setUnread(count)
      if (seenId.current === null) {
        if (!count) { seenId.current = 0; return }
        const page = await listNotifications(token, { limit: 5 })
        seenId.current = page.items[0]?.id ?? 0
        return
      }
      if (!grew) return
      const page = await listNotifications(token, { limit: 5, unreadOnly: true })
      const fresh = newestUnseen(page.items, seenId.current)
      if (fresh) {
        seenId.current = fresh.id
        matches.current.clear() // prices moved: entry points re-read their watch
        setWatchVersion(v => v + 1)
        announce(fresh)
      }
    } catch { /* offline or signed out — the next poll tries again */ }
  }, [token, announce])

  const refresh = useCallback(() => {
    if (!token) return Promise.resolve()
    if (!inflight.current) {
      inflight.current = doRefresh().finally(() => { inflight.current = null })
    }
    return inflight.current
  }, [token, doRefresh])

  /** An alert the user has already seen elsewhere (e.g. "Check now"). */
  const markSeen = useCallback((id) => {
    seenId.current = Math.max(seenId.current ?? 0, id)
  }, [])

  // Another account: forget what the previous one had seen. Runs before
  // the polling effect below (effects run in order).
  useEffect(() => {
    seenId.current = null
    lastCount.current = 0
  }, [token])

  useEffect(() => {
    if (!token) return undefined
    let timer = null
    const stop = () => { if (timer) { clearInterval(timer); timer = null } }
    const start = () => { stop(); timer = setInterval(refresh, pollMs) }
    const onVisibility = () => {
      if (document.visibilityState === 'visible') { refresh(); start() } else stop()
    }
    const onFocus = () => refresh()
    // One fetch even in a background tab, so the badge is right on arrival;
    // polling itself only runs while visible.
    refresh()
    if (document.visibilityState === 'visible') start()
    document.addEventListener('visibilitychange', onVisibility)
    window.addEventListener('focus', onFocus)
    return () => {
      stop()
      document.removeEventListener('visibilitychange', onVisibility)
      window.removeEventListener('focus', onFocus)
    }
  }, [token, pollMs, refresh])

  const markRead = useCallback(async (ids) => {
    if (!token) return
    try {
      const res = await markNotificationsRead(ids, token)
      lastCount.current = res.unread
      setUnread(res.unread)
    } catch { /* stays unread; harmless */ }
  }, [token])

  const watchFor = useCallback((trip) => {
    const key = `${token}|${tripKey(trip)}`
    if (!matches.current.has(key)) {
      matches.current.set(key, matchFareWatch(trip, token).catch(() => {
        matches.current.delete(key)
        return null
      }))
    }
    return matches.current.get(key)
  }, [token])

  /** After creating / editing / deleting watches: entry points re-read. */
  const watchesChanged = useCallback(() => {
    matches.current.clear()
    setWatchVersion(v => v + 1)
  }, [])

  const shouldOfferBrowserAlerts = useCallback(() =>
    permission === 'default' && !safeStorage(() => localStorage.getItem(PROMPTED_KEY)), [permission])

  const answerBrowserAlerts = useCallback(async (allow) => {
    safeStorage(() => localStorage.setItem(PROMPTED_KEY, '1'))
    if (allow && browserPermission() === 'default') {
      try { setPermission(await window.Notification.requestPermission()) } catch { /* unsupported */ }
    } else {
      setPermission(p => p) // re-render so the prompt hides
    }
  }, [])

  const value = useMemo(() => ({
    unread, refresh, markRead, markSeen, toast, showToast: setToast, dismissToast: () => setToast(null),
    caps, watchFor, watchVersion, watchesChanged, permission,
    shouldOfferBrowserAlerts, answerBrowserAlerts,
  }), [unread, refresh, markRead, markSeen, toast, caps, watchFor, watchVersion, watchesChanged, permission,
    shouldOfferBrowserAlerts, answerBrowserAlerts])

  return <AlertsContext.Provider value={value}>{children}</AlertsContext.Provider>
}

export function useAlerts() {
  return useContext(AlertsContext)
}

/** The user's watch for `trip` (null when not watched), kept fresh. */
export function useWatchFor(trip, enabled = true) {
  const { watchFor, watchVersion } = useAlerts()
  const [watch, setWatch] = useState(null)
  const key = trip ? tripKey(trip) : ''
  useEffect(() => {
    if (!enabled || !trip) { setWatch(null); return undefined }
    let active = true
    watchFor(trip).then(w => { if (active) setWatch(w) })
    return () => { active = false }
  }, [key, enabled, watchVersion, watchFor]) // trip is identified by its key
  return [watch, setWatch]
}
