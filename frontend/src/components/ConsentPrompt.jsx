import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { consentRequired, getConsent, setConsent, telemetryAllowed } from '../telemetry/consent'

export const PRIVACY_POLICY_URL = 'https://github.com/rupakc/travel-planner/blob/main/docs/Privacy.md'

// Fired after any consent change so the prompt and the Preferences switch
// stay in step (consent.js owns the stored value; this only signals).
const CHANGED = 'tp-consent-changed'

export function applyConsent(choice) {
  setConsent(choice)
  try { window.dispatchEvent(new Event(CHANGED)) } catch { /* ignore */ }
}

function useConsentTick() {
  const [, setTick] = useState(0)
  useEffect(() => {
    const on = () => setTick((n) => n + 1)
    window.addEventListener(CHANGED, on)
    return () => window.removeEventListener(CHANGED, on)
  }, [])
}

// A small bottom sheet, not a modal: nothing is blocked or focus-trapped, the
// buttons are plain tab stops. Shown once, only where consent is required.
export default function ConsentPrompt() {
  const { t } = useTranslation('privacy')
  useConsentTick()
  if (!(consentRequired() && getConsent() === null)) return null

  const btn = 'flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-800 ' +
    'bg-white hover:bg-slate-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500'
  return (
    <section
      aria-labelledby="tp-consent-title"
      data-tid="privacy.prompt"
      className="fixed bottom-4 left-4 right-4 z-[60] rounded-2xl border border-slate-200 bg-white p-4 shadow-2xl sm:left-auto sm:w-96"
    >
      <h2 id="tp-consent-title" className="text-sm font-semibold text-slate-800">{t('prompt.title')}</h2>
      <p className="mt-1 text-xs leading-relaxed text-slate-600">
        {t('prompt.body')}{' '}
        <a href={PRIVACY_POLICY_URL} target="_blank" rel="noopener noreferrer" data-tid="privacy.prompt-policy"
          className="font-medium text-teal-700 underline">{t('policy')}</a>
      </p>
      <div className="mt-3 flex gap-2">
        <button type="button" data-tid="privacy.allow" onClick={() => applyConsent('granted')} className={btn}>
          {t('prompt.allow')}
        </button>
        <button type="button" data-tid="privacy.deny" onClick={() => applyConsent('denied')} className={btn}>
          {t('prompt.deny')}
        </button>
      </div>
    </section>
  )
}

// The "Help improve Voyager" switch for Preferences → Privacy.
export function PrivacySwitch() {
  const { t } = useTranslation('privacy')
  useConsentTick()
  const on = telemetryAllowed()
  return (
    <div>
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p id="tp-privacy-switch-label" className="text-sm font-semibold text-slate-800">{t('switch.label')}</p>
          <p className="mt-0.5 text-xs text-slate-500">{t('switch.hint')}</p>
        </div>
        <button
          type="button" role="switch" aria-checked={on} aria-labelledby="tp-privacy-switch-label"
          data-tid="privacy.switch"
          onClick={() => applyConsent(on ? 'denied' : 'granted')}
          className={`relative mt-0.5 h-6 w-11 shrink-0 rounded-full transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 focus-visible:ring-offset-2 ${on ? 'bg-teal-600' : 'bg-slate-300'}`}
        >
          <span aria-hidden="true"
            className={`absolute left-0.5 top-0.5 h-5 w-5 rounded-full bg-[#ffffff] shadow transition-transform ${on ? 'translate-x-5' : ''}`} />
        </button>
      </div>
      <a href={PRIVACY_POLICY_URL} target="_blank" rel="noopener noreferrer" data-tid="privacy.policy"
        className="mt-2 inline-block text-xs font-medium text-teal-700 underline">{t('policy')}</a>
    </div>
  )
}
