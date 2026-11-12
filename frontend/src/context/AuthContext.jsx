import { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react'
import { onSessionRevoked } from '../services/sessionRevoked'
import { loadClientConfig } from '../hooks/useClientConfig'
import { clearUser } from '../offline/packStore'
import { clearOutbox, startAutoFlush } from '../offline/outbox'
import { disableOffline } from '../offline/registerSW'

const AuthContext = createContext(null)

const telemetry = (fn) => { import('../telemetry/client').then(fn).catch(() => {}) }

const readStoredToken = () => { try { return localStorage.getItem('tp_token') } catch { return null } }
const writeStoredToken = (value) => {
  try { if (value) localStorage.setItem('tp_token', value); else localStorage.removeItem('tp_token') } catch { /* private mode */ }
}
// Removes the stored token only while it is still `value`: another tab may
// have stored a fresh token meanwhile, and that one must survive.
const dropStoredToken = (value) => { if (value && readStoredToken() === value) writeStoredToken(null) }

// The signed-in user's basics, kept so the app can open offline (airplane
// mode, a reload of a saved trip): {id, username, display_name, is_admin}.
// Written on every successful load, removed on sign-out.
const USER_CACHE_KEY = 'tp_user_cache'

// The token's claims (uid: user id, sub: username), unverified: only used to
// check that the cached user belongs to this token.
function tokenClaims(tok) {
  try {
    const part = String(tok || '').split('.')[1]
    if (!part) return {}
    const json = atob(part.replace(/-/g, '+').replace(/_/g, '/').padEnd(Math.ceil(part.length / 4) * 4, '='))
    const claims = JSON.parse(json)
    return claims && typeof claims === 'object' ? claims : {}
  } catch { return {} }
}

const writeUserCache = (u) => {
  try {
    if (u && u.id !== null && u.id !== undefined && !u.requires_password_change) {
      localStorage.setItem(USER_CACHE_KEY, JSON.stringify({
        id: u.id, username: u.username, display_name: u.display_name ?? null, is_admin: !!u.is_admin,
      }))
    } else {
      localStorage.removeItem(USER_CACHE_KEY)
    }
  } catch { /* private mode */ }
}
const removeUserCache = () => { try { localStorage.removeItem(USER_CACHE_KEY) } catch { /* private mode */ } }

// The cached user when it belongs to `tok` (its uid/sub claims match), else null.
function readUserCache(tok) {
  try {
    const u = JSON.parse(localStorage.getItem(USER_CACHE_KEY) || 'null')
    if (!u || typeof u !== 'object' || u.id === null || u.id === undefined || !u.username) return null
    const { uid, sub } = tokenClaims(tok)
    if (uid !== undefined && uid !== null && String(uid) !== String(u.id)) return null
    if (sub && sub !== u.username) return null
    return { id: u.id, username: u.username, display_name: u.display_name ?? null, is_admin: !!u.is_admin }
  } catch { return null }
}

// Deletes the signed-out user's offline packs and queued writes, and the user cache.
function clearOfflineData(userId) {
  removeUserCache()
  if (userId === null || userId === undefined) return Promise.resolve()
  return Promise.all([clearUser(userId), clearOutbox(userId)]).then(() => {}, () => {})
}

// features.offline_pack false (the kill switch) unregisters the service worker
// and deletes the offline caches and packs: once per page load.
let offlineKillChecked = false

export function AuthProvider({ children }) {
  const [user, setUser]   = useState(null)
  const [token, setTokenState] = useState(readStoredToken)
  const [preferences, setPreferences] = useState(null)
  const [loading, setLoading] = useState(true)
  // Why the user was signed out without asking ('session_revoked'), for the login page.
  const [signOutReason, setSignOutReason] = useState(null)
  // /auth/me could not be reached (no network): the session is kept, the user
  // comes from tp_user_cache, and it is checked again on `online`.
  const [offline, setOffline] = useState(false)
  const userRef = useRef(null)
  userRef.current = user
  // The token this tab uses right now (synchronously, for listeners), and an
  // epoch that every sign-in / sign-out bumps so a late answer for an older
  // session can't overwrite a newer one.
  const tokenRef = useRef(token)
  const epoch = useRef(0)
  const setToken = useCallback((value) => { tokenRef.current = value; setTokenState(value) }, [])

  // Loads the user (and preferences) for `tok`. When /auth/me never answers
  // (offline) the session is kept: the token stays and the user comes from
  // tp_user_cache. Any HTTP failure (401, 403, …) signs this tab out without
  // deleting a token another tab stored.
  const loadSession = useCallback((tok) => {
    const mine = ++epoch.current
    let answered = false
    let revoked = false
    return fetch('/api/auth/me', { headers: { Authorization: `Bearer ${tok}` } })
      .then(async r => {
        answered = true
        if (r.ok) return r.json()
        const body = r.status === 401 ? await r.json().catch(() => ({})) : {}
        revoked = body?.error_code === 'session_revoked'
        if (revoked && epoch.current === mine) setSignOutReason('session_revoked')
        return Promise.reject()
      })
      .then(u => {
        if (epoch.current !== mine) return
        setUser(u)
        setOffline(false)
        writeUserCache(u)
        if (u.requires_password_change) return
        // A failed preferences load never ends the session.
        return fetch('/api/preferences', { headers: { Authorization: `Bearer ${tok}` } })
          .then(r => r.ok ? r.json() : null)
          .then(p => { if (p && epoch.current === mine) setPreferences(p) })
          .catch(() => {})
      })
      .catch(() => {
        if (epoch.current !== mine) return
        if (!answered) {
          const cached = readUserCache(tok)
          setUser(current => current || cached)
          setOffline(true)
          return
        }
        const uid = userRef.current?.id ?? tokenClaims(tok).uid
        if (revoked) clearOfflineData(uid)
        else removeUserCache()
        dropStoredToken(tok)
        setToken(null)
        setUser(null)
        setOffline(false)
      })
  }, [setToken])

  // While offline, check the session again as soon as the network is back
  // (`online`), or when the tab is shown again: the server may have been the
  // one unreachable (a reboot window) while the device stayed online.
  useEffect(() => {
    if (!offline) return undefined
    const recheck = () => { const tok = tokenRef.current; if (tok) loadSession(tok) }
    const onVisible = () => { if (document.visibilityState === 'visible') recheck() }
    window.addEventListener('online', recheck)
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      window.removeEventListener('online', recheck)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [offline, loadSession])

  // The offline kill switch (features.offline_pack false in /config).
  useEffect(() => {
    let live = true
    loadClientConfig().then((config) => {
      if (!live || offlineKillChecked || config?.features?.offline_pack !== false) return
      offlineKillChecked = true
      disableOffline().catch(() => {})
    }).catch(() => {})
    return () => { live = false }
  }, [])

  // Queued offline writes go out on `online` and every minute while queued.
  const userId = user?.id
  useEffect(() => {
    if (userId === null || userId === undefined) return undefined
    return startAutoFlush(() => tokenRef.current, () => userRef.current?.id)
  }, [userId])

  useEffect(() => {
    if (!token) { setLoading(false); return }
    // Only the latest attempt ends loading: StrictMode runs this twice, and the
    // superseded first run must not report "loaded, nobody signed in".
    const pending = loadSession(token)
    const mine = epoch.current
    pending.finally(() => { if (epoch.current === mine) setLoading(false) })
  }, []) // only on mount

  // A request answered 401 session_revoked (password reset, "sign out
  // everywhere" or a password change elsewhere). Only this tab's own token
  // counts: a late answer for an older token is ignored. When another tab has
  // meanwhile stored a different token (it reset or changed the password),
  // this tab adopts it; otherwise it signs out and says why.
  useEffect(() => onSessionRevoked((used) => {
    const current = tokenRef.current
    if (!current || (used && used !== current)) return
    const stored = readStoredToken()
    if (stored && stored !== current) {
      setToken(stored)
      loadSession(stored)
      return
    }
    epoch.current += 1
    clearOfflineData(userRef.current?.id ?? tokenClaims(current).uid)
    dropStoredToken(current)
    setToken(null)
    setUser(null)
    setOffline(false)
    setLoading(false)
    setSignOutReason('session_revoked')
  }), [loadSession, setToken])

  // Adopts a Session ({access_token, user}): stores the token, sets the user,
  // loads preferences. Used by login and every sign-up / OAuth / reset flow.
  const applySession = useCallback(async (session) => {
    const accessToken = session.access_token
    epoch.current += 1
    writeStoredToken(accessToken)
    setToken(accessToken)
    setUser(session.user)
    setOffline(false)
    writeUserCache(session.user)
    setLoading(false)
    setSignOutReason(null)
    if (!session.user?.requires_password_change) {
      try {
        const prefsRes = await fetch('/api/preferences', { headers: { Authorization: `Bearer ${accessToken}` } })
        if (prefsRes.ok) setPreferences(await prefsRes.json())
      } catch {}
    }
    telemetry((m) => m.setUserPresent(true))
    return session.user
  }, [setToken])

  const login = async (username, password) => {
    const res = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      const failure = new Error(err.detail || 'Login failed')
      // Structured fields (e.g. account_pending + email_hint) for the login page.
      failure.code = err.error_code || null
      failure.extra = err
      throw failure
    }
    return applySession(await res.json())
  }

  const refreshUser = useCallback(async () => {
    if (!token) return
    try {
      const r = await fetch('/api/auth/me', { headers: { Authorization: `Bearer ${token}` } })
      if (r.ok) {
        const u = await r.json()
        setUser(u)
        writeUserCache(u)
      }
    } catch {}
  }, [token])

  const updateTokenAfterPasswordChange = (newToken) => {
    epoch.current += 1
    writeStoredToken(newToken)
    setToken(newToken)
    const current = userRef.current
    const next = current ? { ...current, requires_password_change: false } : current
    userRef.current = next
    setUser(next)
    writeUserCache(next)
  }

  const setUserEmail = (email) => setUser(u => (u ? { ...u, email } : u))

  // Signs out and deletes this user's offline packs and queued writes
  // (resolves when they are gone).
  const logout = () => {
    const uid = userRef.current?.id ?? tokenClaims(tokenRef.current).uid
    epoch.current += 1
    writeStoredToken(null)
    setToken(null)
    setUser(null)
    setOffline(false)
    setLoading(false)
    return clearOfflineData(uid)
  }

  const refreshPreferences = useCallback(() => {
    if (!token) return Promise.resolve()
    return fetch('/api/preferences', { headers: { Authorization: `Bearer ${token}` } })
      .then(r => r.ok ? r.json() : null)
      .then(p => { if (p) setPreferences(p) })
  }, [token])

  const updatePreferences = useCallback((prefs) => {
    if (!token) return Promise.resolve()
    return fetch('/api/preferences', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify(prefs),
    })
      .then(r => r.ok ? r.json() : null)
      .then(p => { if (p) setPreferences(p) })
  }, [token])

  return (
    <AuthContext.Provider value={{
      user,
      token,
      login,
      applySession,
      refreshUser,
      accountVerified: user?.account_verified !== false,
      logout,
      signOutReason,
      offline,
      loading,
      isAuthenticated: !!user,
      isAdmin: !!user?.is_admin,
      requiresPasswordChange: !!user?.requires_password_change,
      updateTokenAfterPasswordChange,
      setUserEmail,
      preferences,
      refreshPreferences,
      updatePreferences,
    }}>
      {children}
    </AuthContext.Provider>
  )
}

export const useAuth = () => {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}

/** Auth state when present, else {} (components that may render outside the
 * provider, e.g. in isolated tests, and simply hide signed-in features). */
export const useOptionalAuth = () => useContext(AuthContext) || {}
