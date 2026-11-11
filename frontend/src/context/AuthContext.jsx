import { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react'
import { onSessionRevoked } from '../services/sessionRevoked'

const AuthContext = createContext(null)

const telemetry = (fn) => { import('../telemetry/client').then(fn).catch(() => {}) }

const readStoredToken = () => { try { return localStorage.getItem('tp_token') } catch { return null } }
const writeStoredToken = (value) => {
  try { if (value) localStorage.setItem('tp_token', value); else localStorage.removeItem('tp_token') } catch { /* private mode */ }
}
// Removes the stored token only while it is still `value`: another tab may
// have stored a fresh token meanwhile, and that one must survive.
const dropStoredToken = (value) => { if (value && readStoredToken() === value) writeStoredToken(null) }

export function AuthProvider({ children }) {
  const [user, setUser]   = useState(null)
  const [token, setTokenState] = useState(readStoredToken)
  const [preferences, setPreferences] = useState(null)
  const [loading, setLoading] = useState(true)
  // Why the user was signed out without asking ('session_revoked'), for the login page.
  const [signOutReason, setSignOutReason] = useState(null)
  // The token this tab uses right now (synchronously, for listeners), and an
  // epoch that every sign-in / sign-out bumps so a late answer for an older
  // session can't overwrite a newer one.
  const tokenRef = useRef(token)
  const epoch = useRef(0)
  const setToken = useCallback((value) => { tokenRef.current = value; setTokenState(value) }, [])

  // Loads the user (and preferences) for `tok`; on failure signs this tab out
  // without deleting a token another tab stored.
  const loadSession = useCallback((tok) => {
    const mine = ++epoch.current
    return fetch('/api/auth/me', { headers: { Authorization: `Bearer ${tok}` } })
      .then(async r => {
        if (r.ok) return r.json()
        const body = r.status === 401 ? await r.json().catch(() => ({})) : {}
        if (body?.error_code === 'session_revoked' && epoch.current === mine) setSignOutReason('session_revoked')
        return Promise.reject()
      })
      .then(u => {
        if (epoch.current !== mine) return
        setUser(u)
        if (u.requires_password_change) return
        return fetch('/api/preferences', { headers: { Authorization: `Bearer ${tok}` } })
          .then(r => r.ok ? r.json() : null)
          .then(p => { if (p && epoch.current === mine) setPreferences(p) })
      })
      .catch(() => {
        if (epoch.current !== mine) return
        dropStoredToken(tok)
        setToken(null)
        setUser(null)
      })
  }, [setToken])

  useEffect(() => {
    if (!token) { setLoading(false); return }
    loadSession(token).finally(() => setLoading(false))
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
    dropStoredToken(current)
    setToken(null)
    setUser(null)
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
      if (r.ok) setUser(await r.json())
    } catch {}
  }, [token])

  const updateTokenAfterPasswordChange = (newToken) => {
    epoch.current += 1
    writeStoredToken(newToken)
    setToken(newToken)
    setUser(u => u ? { ...u, requires_password_change: false } : u)
  }

  const setUserEmail = (email) => setUser(u => (u ? { ...u, email } : u))

  const logout = () => {
    epoch.current += 1
    writeStoredToken(null)
    setToken(null)
    setUser(null)
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
