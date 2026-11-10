// The app's languages, in picker order, by their native names.
export const LANGUAGES = [
  { code: 'en', native: 'English' },
  { code: 'es', native: 'Español' },
  { code: 'de', native: 'Deutsch' },
  { code: 'fr', native: 'Français' },
  { code: 'hi', native: 'हिन्दी' },
  { code: 'zh', native: '中文（简体）' },
  { code: 'bn', native: 'বাংলা' },
]

export const DEFAULT_LANGUAGE = 'en'
export const LANGUAGE_CODES = LANGUAGES.map((l) => l.code)
export const isSupportedLanguage = (code) => LANGUAGE_CODES.includes(code)

// App language → BCP 47 locale for Intl.* and <html lang>.
const INTL_LOCALES = { zh: 'zh-CN', hi: 'hi-IN', bn: 'bn-IN' }
export const intlLocale = (code) => INTL_LOCALES[code] || code || DEFAULT_LANGUAGE

// Scripts Inter doesn't cover: a Noto family is fetched from Google Fonts the
// first time one of these languages is used.
export const SCRIPT_FONTS = {
  hi: 'Noto Sans Devanagari',
  bn: 'Noto Sans Bengali',
  zh: 'Noto Sans SC',
}
