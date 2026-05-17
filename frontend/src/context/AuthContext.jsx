import { createContext, useContext, useState, useEffect, useCallback } from 'react'

const AuthContext = createContext(null)

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
    const data = await res.json()
    localStorage.setItem('tp_token', data.access_token)
    setToken(data.access_token)
    setUser(data.user)
    if (!data.user.requires_password_change) {
      try {
        const prefsRes = await fetch('/api/preferences', { headers: { Authorization: `Bearer ${data.access_token}` } })
        if (prefsRes.ok) setPreferences(await prefsRes.json())
      } catch {}
    }
    return data.user
  }

  const updateTokenAfterPasswordChange = (newToken) => {
    localStorage.setItem('tp_token', newToken)
    setToken(newToken)
    setUser(u => u ? { ...u, requires_password_change: false } : u)
  }

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
      logout,
      loading,
      isAuthenticated: !!user,
      isAdmin: !!user?.is_admin,
      requiresPasswordChange: !!user?.requires_password_change,
      updateTokenAfterPasswordChange,
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
