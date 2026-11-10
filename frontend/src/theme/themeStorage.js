// Theme preference in localStorage (`tp_theme`). Every access is guarded:
// Safari private mode and blocked site data throw, and the app must still work.
export const THEME_KEY = 'tp_theme'
export const THEMES = ['system', 'light', 'dark']
export const DEFAULT_THEME = 'light'

export const isTheme = (t) => THEMES.includes(t)

export function readTheme() {
  try {
    const t = window.localStorage.getItem(THEME_KEY)
    return isTheme(t) ? t : DEFAULT_THEME
  } catch {
    return DEFAULT_THEME
  }
}

export function writeTheme(theme) {
  try {
    window.localStorage.setItem(THEME_KEY, theme)
  } catch {
    // ignore: the choice still applies for this session
  }
}
