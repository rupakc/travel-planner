// Vitest setup: i18n is initialised eagerly in English, so components render
// their English copy and tests can keep querying by English text.
import { initI18n } from '../i18n'

await initI18n({ lng: 'en' })
