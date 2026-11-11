import { useTranslation } from 'react-i18next'
import { LANGUAGES, setLanguage } from '../../i18n'
import { useTheme } from '../../theme/ThemeContext'
import { PrivacySwitch } from '../ConsentPrompt'
import { useAccountSettings } from './SettingsSync'

const FALLBACK_CURRENCIES = ['USD', 'EUR', 'GBP', 'JPY', 'AUD', 'CAD', 'CHF', 'CNY', 'INR', 'BDT', 'MXN', 'BRL', 'SGD', 'AED', 'THB']
const FALLBACK_ZONES = ['UTC', 'America/New_York', 'America/Los_Angeles', 'Europe/London', 'Europe/Berlin', 'Asia/Kolkata', 'Asia/Dhaka', 'Asia/Shanghai', 'Asia/Tokyo', 'Australia/Sydney']

function intlList(key, fallback) {
  try {
    const list = Intl.supportedValuesOf(key)
    if (list?.length) return list
  } catch { /* old browser */ }
  return fallback
}

function deviceZone() {
  try { return Intl.DateTimeFormat().resolvedOptions().timeZone || null } catch { return null }
}

const FIELD = 'mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800'

function Select({ id, label, value, onChange, options, tid }) {
  return (
    <label className="block text-sm font-medium text-slate-700">
      {label}
      <select id={id} data-tid={tid} value={value} onChange={(e) => onChange(e.target.value)} className={FIELD}>
        {options.map(([v, text]) => <option key={v} value={v}>{text}</option>)}
      </select>
    </label>
  )
}

function Switch({ id, tid, label, hint, on, onChange }) {
  return (
    <div className="flex items-start justify-between gap-4">
      <div className="min-w-0">
        <p id={id} className="text-sm font-semibold text-slate-800">{label}</p>
        <p className="mt-0.5 text-xs text-slate-500">{hint}</p>
      </div>
      <button type="button" role="switch" aria-checked={on} aria-labelledby={id} data-tid={tid}
        onClick={() => onChange(!on)}
        className={`relative mt-0.5 h-6 w-11 shrink-0 rounded-full transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 focus-visible:ring-offset-2 ${on ? 'bg-teal-600' : 'bg-slate-300'}`}>
        <span aria-hidden="true"
          className={`absolute left-0.5 top-0.5 h-5 w-5 rounded-full bg-[#ffffff] shadow transition-transform ${on ? 'translate-x-5' : ''}`} />
      </button>
    </div>
  )
}

// `account` is null on a backend without accounts: render nothing.
export default function SettingsSection({ account }) {
  const { t, i18n } = useTranslation('accountSettings')
  const { settings, update } = useAccountSettings()
  const { theme, setTheme } = useTheme()
  if (!account) return null

  const language = i18n.resolvedLanguage || i18n.language
  const device = deviceZone()
  const zones = intlList('timeZone', FALLBACK_ZONES)
  const zone = settings.timezone || device || 'UTC'
  const zoneOptions = zones.includes(zone) ? zones : [zone, ...zones]
  const currencies = intlList('currency', FALLBACK_CURRENCIES)
  const currencyOptions = currencies.includes(settings.currency) ? currencies : [settings.currency, ...currencies]

  return (
    <section data-tid="settings.section" aria-labelledby="settings-title"
      className="mx-auto mt-6 max-w-2xl rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <h2 id="settings-title" className="text-lg font-semibold text-slate-800">{t('title')}</h2>
      <p className="mt-0.5 text-sm text-slate-500">{t('hint')}</p>

      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <Select tid="settings.language" label={t('language')} value={language}
          onChange={(v) => setLanguage(v)} options={LANGUAGES.map((l) => [l.code, l.native])} />
        <Select tid="settings.theme" label={t('theme.label')} value={theme}
          onChange={(v) => setTheme(v)}
          options={['system', 'light', 'dark'].map((v) => [v, t(`theme.${v}`)])} />
        <Select tid="settings.currency" label={t('currency')} value={settings.currency}
          onChange={(v) => update({ currency: v })} options={currencyOptions.map((c) => [c, c])} />
        <Select tid="settings.units" label={t('units.label')} value={settings.units}
          onChange={(v) => update({ units: v })}
          options={['metric', 'imperial'].map((v) => [v, t(`units.${v}`)])} />
        <div>
          <Select tid="settings.timezone" label={t('timezone.label')} value={zone}
            onChange={(v) => update({ timezone: v })} options={zoneOptions.map((z) => [z, z])} />
          {device && device !== settings.timezone && (
            <button type="button" data-tid="settings.timezone.device" onClick={() => update({ timezone: device })}
              className="mt-1 text-xs font-medium text-teal-700 underline">
              {t('timezone.useDevice', { zone: device })}
            </button>
          )}
        </div>
        <Select tid="settings.visibility" label={t('visibility.label')} value={settings.profile_visibility}
          onChange={(v) => update({ profile_visibility: v })}
          options={['public', 'followers', 'private'].map((v) => [v, t(`visibility.${v}`)])} />
      </div>

      <div className="mt-5 space-y-4">
        <Switch id="settings-hide-game" tid="settings.hide_game" label={t('hideGame.label')} hint={t('hideGame.hint')}
          on={settings.hide_game} onChange={(v) => update({ hide_game: v })} />
        <Switch id="settings-hide-community" tid="settings.hide_community" label={t('hideCommunity.label')}
          hint={t('hideCommunity.hint')} on={settings.hide_community}
          onChange={(v) => update({ hide_community: v })} />
        <PrivacySwitch />
      </div>
    </section>
  )
}
