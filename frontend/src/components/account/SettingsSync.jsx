import { useEffect, useRef, useSyncExternalStore } from 'react'
import i18n, { setLanguage } from '../../i18n'
import { isSupportedLanguage } from '../../i18n/languages'
import { useOptionalAuth } from '../../context/AuthContext'
import { useTheme } from '../../theme/ThemeContext'
import { THEME_KEY, isTheme } from '../../theme/themeStorage'
import { getConsent, telemetryAllowed } from '../../telemetry/consent'
import { getSettings, patchSettings } from '../../services/accountApi'
import { useClientConfig, featureOn } from '../../hooks/useClientConfig'

export const DEFAULT_SETTINGS = {
  language: null, theme: 'system', currency: 'USD', units: 'metric', timezone: null,
  hide_game: false, hide_community: false, profile_visibility: 'public', telemetry_opt_out: false,
}

const DEBOUNCE_MS = 1000
const CONSENT_EVENT = 'tp-consent-changed'

// Module-level store (no provider needed): `settings` mirrors the server,
// `token` is set only while syncing is active (signed in, endpoint exists).
let settings = DEFAULT_SETTINGS
let token = null
let pending = {}
let timer = null
// True while the signed-in user's settings are being fetched, so consumers
// that must honour hide_game (the celebration) can wait for them.
let loading = false
const listeners = new Set()

const emitChange = () => listeners.forEach((l) => l())
const subscribe = (l) => { listeners.add(l); return () => listeners.delete(l) }
const getSnapshot = () => settings
const setLoading = (on) => { if (loading !== on) { loading = on; emitChange() } }

function inactive() {
  token = null
  pending = {}
  clearTimeout(timer)
  timer = null
}

function flush() {
  timer = null
  const body = pending
  pending = {}
  if (!token || !Object.keys(body).length) return
  const used = token
  patchSettings(used, body).catch((err) => {
    if (err?.status === 404 && token === used) inactive()
  })
}

function update(patch) {
  settings = { ...settings, ...patch }
  emitChange()
  if (!token) return
  pending = { ...pending, ...patch }
  clearTimeout(timer)
  timer = setTimeout(flush, DEBOUNCE_MS)
}

/** Clears the store (sign-out) — and between tests. */
export function resetAccountSettings() {
  inactive()
  loading = false
  settings = DEFAULT_SETTINGS
  emitChange()
}

/** Whether the settings fetch is still in flight (read inside effects). */
export const settingsLoading = () => loading

/** Re-renders when the settings fetch starts or ends. */
export function useSettingsLoading() {
  return useSyncExternalStore(subscribe, settingsLoading, settingsLoading)
}

export function useAccountSettings() {
  const current = useSyncExternalStore(subscribe, getSnapshot, getSnapshot)
  return { settings: current, update }
}

function storedValue(key) {
  try { return window.localStorage.getItem(key) } catch { return null }
}

export default function SettingsSync() {
  const auth = useOptionalAuth()
  const accessToken = auth?.token || null
  // /account/settings exists only where /config says features.accounts.
  const { config, loaded } = useClientConfig()
  const accounts = featureOn(config, 'accounts')
  const { theme, setTheme } = useTheme()
  const synced = useRef(false)
  const lastTheme = useRef(theme)
  const lastLang = useRef(null)
  const themeNow = useRef(theme)
  themeNow.current = theme

  // Sign-in: GET and apply; the server wins unless it holds no choice.
  useEffect(() => {
    synced.current = false
    if (!accessToken) { resetAccountSettings(); return undefined }
    if (!loaded) { setLoading(true); return undefined }   // until /config says
    if (!accounts) { resetAccountSettings(); return undefined }
    let cancelled = false
    setLoading(true)
    getSettings(accessToken).then((server) => {
      if (cancelled) return
      if (!server || typeof server !== 'object') { setLoading(false); return }
      token = accessToken
      settings = { ...DEFAULT_SETTINGS, ...server }
      loading = false   // together with the settings: one change, hide_game already in
      emitChange()
      const up = {}

      if (isTheme(server.theme) && server.theme !== 'system') {
        lastTheme.current = server.theme
        if (server.theme !== themeNow.current) setTheme(server.theme)
      } else {
        lastTheme.current = themeNow.current
        const stored = storedValue(THEME_KEY)
        if (isTheme(stored) && stored !== 'system') up.theme = stored
      }

      const lang = i18n.resolvedLanguage || i18n.language
      if (isSupportedLanguage(server.language)) {
        lastLang.current = server.language
        if (server.language !== lang) setLanguage(server.language)
      } else {
        lastLang.current = lang
        if (isSupportedLanguage(storedValue('tp_lang'))) up.language = lang
      }

      // The device's consent stays the source of truth: only mirror it.
      if (getConsent() !== null && server.telemetry_opt_out !== !telemetryAllowed()) {
        up.telemetry_opt_out = !telemetryAllowed()
      }
      synced.current = true
      if (Object.keys(up).length) update(up)
    }).catch(() => { if (!cancelled) setLoading(false) /* 404 (old backend) or offline: stay inactive */ })
    return () => { cancelled = true; inactive(); setLoading(false) }
  }, [accessToken, loaded, accounts, setTheme])

  // Theme changes from anywhere.
  useEffect(() => {
    if (!synced.current || theme === lastTheme.current) return
    lastTheme.current = theme
    if (token) update({ theme })
  }, [theme])

  // Language changes from anywhere (the NavBar picker, the section).
  useEffect(() => {
    const onLang = (lng) => {
      const code = String(lng || '').split('-')[0]
      if (!synced.current || !isSupportedLanguage(code) || code === lastLang.current) return
      lastLang.current = code
      if (token) update({ language: code })
    }
    i18n.on('languageChanged', onLang)
    return () => i18n.off('languageChanged', onLang)
  }, [])

  // The telemetry switch flips local consent; mirror it to the server.
  useEffect(() => {
    const onConsent = () => {
      if (!synced.current || !token) return
      const opt = !telemetryAllowed()
      if (opt !== settings.telemetry_opt_out) update({ telemetry_opt_out: opt })
    }
    window.addEventListener(CONSENT_EVENT, onConsent)
    return () => window.removeEventListener(CONSENT_EVENT, onConsent)
  }, [])

  return null
}
