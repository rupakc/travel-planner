import { useEffect, useRef, useState } from 'react'
import { X } from 'lucide-react'
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

// "Privacy choices" (footer, every page): reopens the sheet below, showing the
// current choice, for any visitor, signed in or not.
const OPEN = 'tp-consent-open'

export function openPrivacyChoices() {
  try { window.dispatchEvent(new Event(OPEN)) } catch { /* ignore */ }
}

// A small bottom sheet, not a modal: nothing is blocked or focus-trapped, the
// buttons are plain tab stops. Shown once where consent is required, and
// again whenever "Privacy choices" is used. Compact on phones, with an
// in-flow spacer of its height so the bottom of the page can scroll clear.
export default function ConsentPrompt() {
  const { t } = useTranslation(['privacy', 'misc'])
  useConsentTick()
  const [reopened, setReopened] = useState(false)
  const [height, setHeight] = useState(0)
  const ref = useRef(null)

  useEffect(() => {
    const open = () => setReopened(true)
    const close = () => setReopened(false)
    window.addEventListener(OPEN, open)
    window.addEventListener(CHANGED, close)
    return () => {
      window.removeEventListener(OPEN, open)
      window.removeEventListener(CHANGED, close)
    }
  }, [])

  const firstRun = consentRequired() && getConsent() === null
  const shown = firstRun || reopened

  useEffect(() => {
    const el = ref.current
    if (!shown || !el) return undefined
    const measure = () => setHeight(el.offsetHeight || 0)
    measure()
    if (reopened) {
      try { el.focus({ preventScroll: true }) } catch { /* ignore */ }
    }
    if (typeof ResizeObserver !== 'function') return undefined
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  }, [shown, reopened])

  if (!shown) return null

  // Reopened: the buttons show what is in force now (opted out until chosen
  // where consent is required).
  const current = reopened ? (telemetryAllowed() ? 'granted' : 'denied') : null
  const btn = (choice) => 'flex-1 rounded-lg border px-3 py-1.5 text-sm font-semibold sm:py-2 ' +
    'focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 ' +
    (current === choice
      ? 'border-teal-600 bg-teal-50 text-teal-800 ring-1 ring-teal-600'
      : 'border-slate-300 bg-white text-slate-800 hover:bg-slate-50')
  return (
    <>
      <div aria-hidden="true" className="sm:hidden" style={{ height: height ? height + 24 : 0 }} />
      <section
        ref={ref}
        tabIndex={-1}
        aria-labelledby="tp-consent-title"
        data-tid="privacy.prompt"
        className="fixed bottom-3 left-3 right-3 z-40 rounded-2xl border border-slate-200 bg-white p-3 shadow-2xl focus:outline-none sm:bottom-4 sm:left-auto sm:right-4 sm:w-96 sm:p-4"
      >
        <div className="flex items-start gap-2">
          <h2 id="tp-consent-title"
            className="min-w-0 flex-1 truncate text-sm font-semibold text-slate-800 sm:whitespace-normal">
            {t('prompt.title')}
          </h2>
          {reopened && (
            <button type="button" data-tid="privacy.close" onClick={() => setReopened(false)}
              aria-label={t('misc:feedback.close')}
              className="-m-1 shrink-0 rounded p-1 text-slate-500 hover:text-slate-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500">
              <X size={16} aria-hidden="true" />
            </button>
          )}
        </div>
        <p className="mt-1 text-xs leading-snug text-slate-600 sm:leading-relaxed">
          {t('prompt.body')}{' '}
          <a href={PRIVACY_POLICY_URL} target="_blank" rel="noopener noreferrer" data-tid="privacy.prompt-policy"
            className="font-medium text-teal-700 underline">{t('policy')}</a>
        </p>
        <div className="mt-2 flex gap-2 sm:mt-3">
          <button type="button" data-tid="privacy.allow" aria-pressed={current ? current === 'granted' : undefined}
            onClick={() => applyConsent('granted')} className={btn('granted')}>
            {t('prompt.allow')}
          </button>
          <button type="button" data-tid="privacy.deny" aria-pressed={current ? current === 'denied' : undefined}
            onClick={() => applyConsent('denied')} className={btn('denied')}>
            {t('prompt.deny')}
          </button>
        </div>
      </section>
    </>
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
