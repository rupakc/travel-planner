import { createContext, useContext, useState, useEffect, useCallback } from 'react'

const AuthContext = createContext(null)

const telemetry = (fn) => { import('../telemetry/client').then(fn).catch(() => {}) }

export function AuthProvider({ children }) {
  const [user, setUser]   = useState(null)
  const [token, setToken] = useState(() => localStorage.getItem('tp_token'))
  const [preferences, setPreferences] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!token) { setLoading(false); return }
    fetch('/api/auth/me', { headers: { Authorization: `Bearer ${token}` } })
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(u => {
        setUser(u)
        if (u.requires_password_change) return
        return fetch('/api/preferences', { headers: { Authorization: `Bearer ${token}` } })
          .then(r => r.ok ? r.json() : null)
          .then(p => { if (p) setPreferences(p) })
      })
      .catch(() => { localStorage.removeItem('tp_token'); setToken(null) })
      .finally(() => setLoading(false))
  }, []) // only on mount

  // Adopts a Session ({access_token, user}): stores the token, sets the user,
  // loads preferences. Used by login and every sign-up / OAuth / reset flow.
  const applySession = useCallback(async (session) => {
    const accessToken = session.access_token
    localStorage.setItem('tp_token', accessToken)
    setToken(accessToken)
    setUser(session.user)
    if (!session.user?.requires_password_change) {
      try {
        const prefsRes = await fetch('/api/preferences', { headers: { Authorization: `Bearer ${accessToken}` } })
        if (prefsRes.ok) setPreferences(await prefsRes.json())
      } catch {}
    }
    telemetry((m) => m.setUserPresent(true))
    return session.user
  }, [])

  const login = async (username, password) => {
    const res = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    })
    if (!res.ok) {
      const err = await res.json()
      throw new Error(err.detail || 'Login failed')
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
    localStorage.setItem('tp_token', newToken)
    setToken(newToken)
    setUser(u => u ? { ...u, requires_password_change: false } : u)
  }

  const setUserEmail = (email) => setUser(u => (u ? { ...u, email } : u))

  const logout = () => {
    localStorage.removeItem('tp_token')
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
