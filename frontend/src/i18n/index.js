// i18next set-up. English ships in the main bundle for every namespace; the
// other languages are separate chunks fetched on first use. Keys follow
// `ns:area.thing` (e.g. `common:nav.search`), plurals use the JSON v4
// suffixes (`_one`, `_other`, …) and interpolation is `{{name}}`.
import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import {
  DEFAULT_LANGUAGE, LANGUAGE_CODES, SCRIPT_FONTS, intlLocale, isSupportedLanguage,
} from './languages'

import { setErrorTranslator } from '../utils/httpError'

export { LANGUAGES } from './languages'

// Legacy error paths (fetch, the old axios client, the SSE workers' errors)
// translate `error_code` through this.
setErrorTranslator((key, options) => i18n.t(key, options))

const STORAGE_KEY = 'tp_lang'

const nsOf = (path) => path.split('/').pop().replace(/\.json$/, '')

const enModules = import.meta.glob('./locales/en/*.json', { eager: true })
const lazyModules = import.meta.glob(['./locales/*/*.json', '!./locales/en/*.json'])

export const NAMESPACES = Object.keys(enModules).map(nsOf).sort()

const enResources = Object.fromEntries(
  Object.entries(enModules).map(([path, mod]) => [nsOf(path), mod.default ?? mod]),
)

// i18next backend that resolves a (language, namespace) pair to its lazy
// chunk. A pair with no file resolves empty, so every key falls back to `en`.
const lazyBackend = {
  type: 'backend',
  init() {},
  read(lng, ns, callback) {
    const loader = lazyModules[`./locales/${lng}/${ns}.json`]
    if (!loader) { callback(null, {}); return }
    loader().then(
      (mod) => callback(null, mod.default ?? mod),
      // A failed chunk (offline, stale deploy) is not fatal: English shows.
      () => callback(null, {}),
    )
  },
}

function readStored() {
  try { return localStorage.getItem(STORAGE_KEY) } catch { return null }
}

// tp_lang → navigator.languages (base tag, so `zh-TW` → `zh`) → en.
export function detectLanguage() {
  const stored = readStored()
  if (isSupportedLanguage(stored)) return stored
  try {
    const prefs = navigator.languages?.length ? navigator.languages : [navigator.language]
    for (const tag of prefs) {
      const base = String(tag || '').toLowerCase().split('-')[0]
      if (isSupportedLanguage(base)) return base
    }
  } catch { /* no navigator */ }
  return DEFAULT_LANGUAGE
}

function loadScriptFont(lng) {
  const family = SCRIPT_FONTS[lng]
  if (!family || typeof document === 'undefined') return
  const id = `tp-font-${lng}`
  if (document.getElementById(id)) return
  const link = document.createElement('link')
  link.id = id
  link.rel = 'stylesheet'
  link.href = `https://fonts.googleapis.com/css2?family=${family.replace(/ /g, '+')}:wght@400;500;600;700&display=swap`
  document.head.appendChild(link)
  // Inter and Sora have no glyphs for this script; put the Noto family next
  // in the stacks so the browser falls back to it rather than a system font.
  const style = document.createElement('style')
  style.id = `${id}-stack`
  style.textContent =
    `html:lang(${lng}) body,html:lang(${lng}) .font-sans{font-family:Inter,"${family}",ui-sans-serif,system-ui,sans-serif}` +
    `html:lang(${lng}) .font-display{font-family:Sora,"${family}",ui-sans-serif,system-ui,sans-serif}`
  document.head.appendChild(style)
}

function applyLanguage(lng) {
  if (typeof document === 'undefined') return
  try {
    document.documentElement.lang = intlLocale(lng)
    loadScriptFont(lng)
  } catch { /* never break rendering over this */ }
}

// Telemetry is called through import() and never awaited: it can't delay the
// switch, and a failing SDK is ignored. The SDK is in the main bundle anyway
// (statically imported via ConsentPrompt -> telemetry/consent.js), so this
// import() does not split it into its own chunk.
function report(event, props) {
  import('../telemetry/client')
    .then((m) => m.emit(event, props))
    .catch(() => {})
}

let initPromise = null

export function initI18n({ lng } = {}) {
  if (initPromise) return initPromise
  i18n.on('languageChanged', applyLanguage)
  initPromise = i18n
    .use(lazyBackend)
    .use(initReactI18next)
    .init({
      lng: isSupportedLanguage(lng) ? lng : detectLanguage(),
      resources: { en: enResources },
      partialBundledLanguages: true,
      ns: NAMESPACES,
      defaultNS: 'common',
      fallbackNS: false,
      fallbackLng: DEFAULT_LANGUAGE,
      supportedLngs: LANGUAGE_CODES,
      load: 'languageOnly',
      returnNull: false,
      returnEmptyString: false,
      interpolation: { escapeValue: false },
      // Render English straight away while another language's chunk loads,
      // instead of suspending the tree.
      react: { useSuspense: false },
    })
    .then(() => {})
  return initPromise
}

// Switches language, remembers it in tp_lang and reports the change.
export function setLanguage(code) {
  if (!isSupportedLanguage(code)) return Promise.resolve()
  const from = i18n.resolvedLanguage || i18n.language
  try { localStorage.setItem(STORAGE_KEY, code) } catch { /* storage blocked */ }
  if (from !== code) report('language_change', { lang: code })
  return i18n.changeLanguage(code).then(() => {})
}

export default i18n
