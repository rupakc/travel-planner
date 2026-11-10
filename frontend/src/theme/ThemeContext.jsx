import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import tokens from '../../design/tokens.json'
import { DEFAULT_THEME, isTheme, readTheme, writeTheme } from './themeStorage'

// Browser chrome colour (<meta name="theme-color">) per resolved theme.
export const THEME_COLOR = { light: '#ffffff', dark: tokens.dark.white }

const QUERY = '(prefers-color-scheme: dark)'

function systemMql() {
  try {
    return typeof window !== 'undefined' && typeof window.matchMedia === 'function'
      ? window.matchMedia(QUERY)
      : null
  } catch {
    return null
  }
}

function applyTheme(resolved) {
  const root = document.documentElement
  root.classList.toggle('dark', resolved === 'dark')
  root.style.colorScheme = resolved
  const meta = document.querySelector('meta[name="theme-color"]')
  if (meta) meta.setAttribute('content', THEME_COLOR[resolved])
}

const ThemeContext = createContext({
  theme: DEFAULT_THEME,
  resolved: 'light',
  setTheme: () => {},
})

export function ThemeProvider({ children }) {
  const [theme, setThemeState] = useState(readTheme)
  const [systemDark, setSystemDark] = useState(() => Boolean(systemMql()?.matches))

  useEffect(() => {
    const mql = systemMql()
    if (!mql) return undefined
    const onChange = (e) => setSystemDark(Boolean(e.matches))
    setSystemDark(Boolean(mql.matches))
    if (mql.addEventListener) mql.addEventListener('change', onChange)
    else if (mql.addListener) mql.addListener(onChange) // Safari < 14
    return () => {
      if (mql.removeEventListener) mql.removeEventListener('change', onChange)
      else if (mql.removeListener) mql.removeListener(onChange)
    }
  }, [])

  const resolved = theme === 'system' ? (systemDark ? 'dark' : 'light') : theme

  useEffect(() => {
    applyTheme(resolved)
  }, [resolved])

  const setTheme = useCallback((t) => {
    if (!isTheme(t)) return
    setThemeState(t)
    writeTheme(t)
  }, [])

  const value = useMemo(() => ({ theme, resolved, setTheme }), [theme, resolved, setTheme])
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

export function useTheme() {
  return useContext(ThemeContext)
}
