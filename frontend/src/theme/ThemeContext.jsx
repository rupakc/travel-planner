// STUB for Task 7 — replaced by Task 4's ThemeContext at merge.
// Same interface: useTheme() -> { theme: 'system'|'light'|'dark',
// resolved: 'light'|'dark', setTheme(t) }, persisted in tp_theme, applied as
// `html.dark`. Light is the default.
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'

const KEY = 'tp_theme'
const THEMES = ['system', 'light', 'dark']
const ThemeContext = createContext(null)

function readStored() {
  try {
    const v = localStorage.getItem(KEY)
    return THEMES.includes(v) ? v : 'light'
  } catch { return 'light' }
}

function systemDark() {
  try { return window.matchMedia('(prefers-color-scheme: dark)').matches } catch { return false }
}

const resolve = (theme) => (theme === 'system' ? (systemDark() ? 'dark' : 'light') : theme)
const applyClass = (resolved) => {
  try { document.documentElement.classList.toggle('dark', resolved === 'dark') } catch { /* no DOM */ }
}
const persist = (t) => {
  try { localStorage.setItem(KEY, t) } catch { /* storage blocked */ }
}

function useThemeState() {
  const [theme, setThemeState] = useState(readStored)
  const resolved = resolve(theme)
  useEffect(() => { applyClass(resolved) }, [resolved])
  const setTheme = useCallback((t) => {
    if (!THEMES.includes(t)) return
    persist(t)
    setThemeState(t)
  }, [])
  return useMemo(() => ({ theme, resolved, setTheme }), [theme, resolved, setTheme])
}

export function ThemeProvider({ children }) {
  const value = useThemeState()
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

// Outside a provider (this stub's main.jsx has none yet) it still works, so
// the branch runs standalone; the provider's value wins whenever present.
export function useTheme() {
  const ctx = useContext(ThemeContext)
  const [fallback, setFallback] = useState(readStored)
  if (ctx) return ctx
  const resolved = resolve(fallback)
  return {
    theme: fallback,
    resolved,
    setTheme: (t) => {
      if (!THEMES.includes(t)) return
      persist(t)
      applyClass(resolve(t))
      setFallback(t)
    },
  }
}
