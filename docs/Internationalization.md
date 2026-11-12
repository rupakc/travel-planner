# Internationalization

The web app ships in seven languages: English (`en`), Spanish (`es`), German (`de`), French (`fr`), Hindi (`hi`), Simplified Chinese (`zh`) and Bengali (`bn`). Translations are machine-drafted and reviewed by a second model; native-speaker review of Hindi, Bengali and Chinese is recommended before promoting the app in those languages.

## Catalogue

Strings live in `frontend/src/i18n/locales/<lang>/<namespace>.json`, loaded with `i18next` 26 and `react-i18next` 17.

| Namespace | Holds |
|---|---|
| `common` | Navigation, buttons, theme and language labels, shared words |
| `search` | Search page (modes, form, recent searches, compare, from-a-link) |
| `results` | Results page and budget planner |
| `chat` | Chat page |
| `plan` | My Plan drawer, cost breakdown, export |
| `itinerary` | Itinerary and timeline |
| `alerts` | Fare and price alerts |
| `account` | Preferences, change password, share |
| `auth` | Login and social sign-in buttons |
| `sections` | Result section chrome (flights, hotels, visa, ...) |
| `privacy` | Consent prompt and Privacy switch |
| `adminTelemetry` | Admin Analytics tab |
| `journey` | Journey tabs, trips hub shell and load states |
| `offline` | Offline banner, queued-write messages |
| `trips`, `trip`, `today`, `prep`, `completeness` | Trips hub, trip screen, Today view, prep checklist, trip-ready meter |
| `offlinePack`, `expenses`, `journal`, `recap` | Offline pack, expenses, journal and place ratings, recap |
| `coach`, `explore`, `nearbyTrip`, `playYou` | Coach marks, Explore header, Near me trip actions, Play and You tabs |
| `misc` | Everything else |

English is lazy per route: `common`, `errors`, `auth`, `journey`, `offline` and `misc`, plus the namespaces the shell renders at first paint, ship in the main bundle; the rest (for example `trip`, `trips`, `prep`, `expenses`, `journal`, `recap`) load when their route is opened (`frontend/src/i18n/routeNamespaces.js`). The other six languages always load on demand.

Conventions:

- Keys are nested objects, referenced as `ns:area.thing` (for example `common:nav.search`). In a component: `const { t } = useTranslation('common')`.
- Interpolation is `{{name}}`. Markup inside a string uses `<tag>` placeholders with `Trans`.
- Plurals use the i18next JSON v4 suffixes on the key: `nights_one`, `nights_other`, and the further forms a language needs (`_few`, `_many`, ...), selected by `{{count}}`.
- Brand names (Apple, Google, Facebook, GitHub) are not translated. Data returned by the AI is not part of the catalogue.

### Adding a string

1. Add the key to `en/<ns>.json` (a new namespace is just a new file in `en/`; it is discovered automatically).
2. Add the same key to the other six languages' files.
3. Run `cd frontend && NODE_OPTIONS=--experimental-require-module npx vitest run src/i18n` (on Node 20.18; plain `npx vitest run` elsewhere).

`src/i18n/catalog.test.js` enforces for every namespace and language: valid JSON; exactly the `en` keys; plural forms equal to the language's `Intl.PluralRules` categories; no empty or non-string value; no value equal to its key; the same `{{placeholders}}` and `<tags>` as `en` (a plural form may drop `{{count}}`); and no file outside `en`'s namespaces.

## Loading and detection

`src/i18n/index.js`: English is bundled for every namespace; the other six languages are separate chunks fetched on first use, and while a chunk loads English shows (no Suspense). A missing chunk (offline, stale deploy) leaves English in place.

The language is chosen from `localStorage['tp_lang']`, else `navigator.languages` (base tag: `zh-TW` becomes `zh`), else `en`. `setLanguage(code)` switches, stores `tp_lang` and emits `language_change`. The picker is `LanguagePicker` (NavBar and Preferences, `data-tid="nav.language"`), listing languages by their native names. `<html lang>` follows the language (`zh-CN`, `hi-IN` and `bn-IN` for the Intl APIs; others the bare code).

Noto Sans Devanagari (`hi`), Noto Sans Bengali (`bn`) and Noto Sans SC (`zh`) are fetched from Google Fonts the first time one of those languages is used, and placed after Inter and Sora in the font stacks.

## Formatting

`src/i18n/format.js` wraps `Intl` and follows the current language; each helper falls back to a readable value instead of throwing:

| Helper | Use |
|---|---|
| `fmtNumber(n, opts)` | Numbers |
| `fmtCurrency(n, currency)` | Currency amounts |
| `fmtDate(d, opts)` | Dates and times (empty string for an invalid date) |
| `fmtRelative(ms)` | Signed offset from now, "3 hours ago" or "in 2 days" (under a minute reads as "now") |

## AI output

The web app adds `locale` (the base language code) to AI-calling requests (`localeField()` in `services/api.js`): `POST /api/search`, `/chat`, `/discover`, `/compare/destination`, `/stress-test` and the single-agent and `/filtered` routes. When it is not `en`, `BaseAgent.execute` appends an instruction to the agent's system prompt asking for every human-readable value in that language while keeping JSON keys, enum values, codes, URLs, prices, currency codes, dates and place names as in English. Absent or `en` leaves prompts unchanged. The search cache keeps a separate entry per language (English keys are unchanged). Field and wire format: [API Reference](API-Reference.md#post-apisearch).

The static Phase 0 tables (visa, SIM, tips, getting around, forex, emergency card) stay in English until the AI result replaces them; only the UI around them is translated.

## For other clients

The catalogue is the web's source for now. Android and iOS get their own generated resources in later phases (see [Feature Parity](Feature-Parity.md)). The language set and the `locale` request field are shared by all clients.
