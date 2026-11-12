// Vitest setup: i18n is initialised in English with every namespace loaded
// (lazy ones included), so components render their English copy straight away
// and tests can keep querying by English text.
import { initI18n } from '../i18n'

await initI18n({ lng: 'en', bundleAll: true })
