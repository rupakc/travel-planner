import { useTranslation } from 'react-i18next'
import { Languages as LanguagesIcon } from 'lucide-react'
import { LANGUAGES, setLanguage } from '../../i18n'

// Language names are always shown natively ("Deutsch", not "German"), so a
// reader can find their language whatever the UI is currently in.
export default function LanguagePicker({ className = '' }) {
  const { t, i18n } = useTranslation('common')
  const current = i18n.resolvedLanguage || i18n.language
  return (
    <label className={`relative flex items-center text-slate-500 ${className}`}>
      <LanguagesIcon size={14} aria-hidden="true" className="pointer-events-none absolute left-1.5" />
      <span className="sr-only">{t('language.label')}</span>
      <select
        data-tid="nav.language"
        value={current}
        onChange={(e) => { setLanguage(e.target.value) }}
        title={t('language.label')}
        className="max-w-[7.5rem] appearance-none truncate rounded-md bg-transparent py-1 pl-6 pr-1 text-xs font-medium text-slate-600 hover:bg-slate-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
      >
        {LANGUAGES.map(({ code, native }) => (
          <option key={code} value={code} lang={code}>{native}</option>
        ))}
      </select>
    </label>
  )
}
