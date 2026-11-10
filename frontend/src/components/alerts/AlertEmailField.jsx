import { useId, useState } from 'react'
import { CheckCircle2, Loader2, Mail } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { axiosErrorDetail } from '../../utils/httpError'

// Mirrors the server's check: local@domain.tld, no spaces
const EMAIL_RE = /^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$/
export const isEmail = (v) => EMAIL_RE.test(String(v || '').trim())

/** Account email used for fare alert emails (saved on its own, right away). */
export default function AlertEmailField({ email, emailAlertsAvailable, onSave, onSaved }) {
  const { t } = useTranslation('alerts')
  const id = useId()
  const [value, setValue] = useState(email || '')
  const [error, setError] = useState(null)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  const submit = async (e) => {
    e.preventDefault()
    const trimmed = value.trim()
    setSaved(false)
    if (trimmed && !isEmail(trimmed)) {
      setError(t('email.invalid'))
      return
    }
    setError(null)
    setSaving(true)
    try {
      const res = await onSave(trimmed)
      setValue(res.email || '')
      onSaved?.(res.email)
      setSaved(true)
    } catch (err) {
      setError(axiosErrorDetail(err).detail || t('email.saveFailed'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <form onSubmit={submit} noValidate>
      <label htmlFor={id} className="mb-1.5 block text-sm font-medium text-gray-700">
        <span className="flex items-center gap-1.5"><Mail size={14} /> {t('email.label')}</span>
      </label>
      <div className="flex flex-col gap-2 sm:flex-row">
        <input id={id} data-tid="alerts.email-input" type="email" autoComplete="email" value={value}
          onChange={e => { setValue(e.target.value); setSaved(false) }}
          aria-invalid={!!error} aria-describedby={`${id}-help`}
          placeholder="name@example.com"
          className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-teal-400" />
        <button type="submit" data-tid="alerts.email-save" disabled={saving}
          className="flex shrink-0 items-center justify-center gap-1.5 rounded-lg border border-teal-600 px-4 py-2.5 text-sm font-semibold text-teal-700 hover:bg-teal-50 disabled:opacity-50">
          {saving && <Loader2 size={14} className="animate-spin" />} {t('email.save')}
        </button>
      </div>
      {error
        ? <p role="alert" id={`${id}-help`} className="mt-1 text-xs text-red-600">{error}</p>
        : (
          <p id={`${id}-help`} className="mt-1 text-xs text-gray-400">
            {saved
              ? <span className="inline-flex items-center gap-1 text-green-600"><CheckCircle2 size={12} /> {t('email.saved')}</span>
              : emailAlertsAvailable
                ? t('email.helpOn')
                : t('email.helpOff')}
          </p>
        )}
    </form>
  )
}
