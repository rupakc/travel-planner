import { Link } from 'react-router-dom'
import { Mail } from 'lucide-react'
import { Trans, useTranslation } from 'react-i18next'

/** One radio choice in a watch dialog ("When the price drops" …). */
export function Option({ checked, onChange, title, children, name, value }) {
  return (
    <label className={`flex cursor-pointer gap-3 rounded-xl border px-3.5 py-3 transition-colors ${checked ? 'border-sky-400 bg-sky-50/70' : 'border-slate-200 hover:border-slate-300'}`}>
      <input type="radio" data-tid={`alerts.option-${value}`} name={name} value={value} checked={checked} onChange={onChange}
        className="mt-0.5 h-4 w-4 accent-sky-600" />
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-medium text-slate-800">{title}</span>
        {children}
      </span>
    </label>
  )
}

/** "Also email me" — disabled, with a Preferences link, until there's an address. */
export function EmailOption({ checked, onChange, email, onClose }) {
  const { t } = useTranslation('alerts')
  const hasEmail = !!email
  return (
    <label className={`mt-3 flex items-start gap-3 ${hasEmail ? 'cursor-pointer' : 'cursor-default'}`}>
      <input type="checkbox" data-tid="alerts.dialog-email" checked={checked && hasEmail} disabled={!hasEmail}
        onChange={e => onChange(e.target.checked)} className="mt-0.5 h-4 w-4 rounded accent-sky-600" />
      <span>
        <span className={`flex items-center gap-1.5 text-sm font-medium ${hasEmail ? 'text-slate-800' : 'text-slate-400'}`}>
          <Mail size={13} /> {t('dialog.email.label')}
        </span>
        <span className="block text-xs text-slate-500">
          {hasEmail
            ? t('dialog.email.sent', { email })
            : (
              <Trans t={t} i18nKey="dialog.email.addFirst"
                components={{ pagelink: <Link to="/preferences" data-tid="alerts.email-preferences" onClick={onClose} className="font-medium text-sky-700 underline underline-offset-2" /> }} />
            )}
        </span>
      </span>
    </label>
  )
}

/** The one-time offer of native browser alerts after a first watch. */
export function BrowserAlertsOffer({ onAnswer }) {
  const { t } = useTranslation('alerts')
  return (
    <div className="mt-3 rounded-xl border border-slate-200 px-4 py-3">
      <p className="text-sm font-medium text-slate-800">{t('dialog.browser.title')}</p>
      <p className="mt-0.5 text-xs text-slate-500">{t('dialog.browser.body')}</p>
      <div className="mt-2.5 flex gap-2">
        <button type="button" data-tid="alerts.browser-allow" onClick={() => onAnswer(true)}
          className="rounded-full bg-slate-900 px-3.5 py-1.5 text-xs font-semibold text-white hover:bg-slate-700">{t('dialog.browser.allow')}</button>
        <button type="button" data-tid="alerts.browser-not-now" onClick={() => onAnswer(false)}
          className="rounded-full px-3.5 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-100">{t('dialog.browser.notNow')}</button>
      </div>
    </div>
  )
}
