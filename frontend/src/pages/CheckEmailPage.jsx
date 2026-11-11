import { useEffect, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { Mail } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { resendVerification } from '../services/authApi'
import { errorText } from '../services/apiError'
import { emit } from '../telemetry/client'

export const RESEND_COOLDOWN_S = 60

// Shown after sign-up. The address comes from router state (`{ email }`) or `?email=`.
export default function CheckEmailPage() {
  const { t } = useTranslation(['verify', 'errors'])
  const location = useLocation()
  const given = location.state?.email || new URLSearchParams(location.search).get('email') || ''
  const [typed, setTyped] = useState('')
  const email = given || typed.trim()
  const [cooldown, setCooldown] = useState(RESEND_COOLDOWN_S)
  const [busy, setBusy] = useState(false)
  const [sent, setSent] = useState(false)
  const [error, setError] = useState('')

  const counting = cooldown > 0
  useEffect(() => {
    if (!counting) return undefined
    const id = setInterval(() => setCooldown((c) => Math.max(0, c - 1)), 1000)
    return () => clearInterval(id)
  }, [counting])

  const resend = async () => {
    if (!email || busy || cooldown > 0) return
    setBusy(true)
    setError('')
    setSent(false)
    try {
      await resendVerification(email)
      setSent(true)
      setCooldown(RESEND_COOLDOWN_S)
      emit('email_verify', { result: 'resent' })
    } catch (err) {
      setError(errorText(t, err))
      if (err?.retryAfter) setCooldown(err.retryAfter)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-teal-50 via-slate-50 to-sky-50 dark:from-slate-900 dark:via-slate-900 dark:to-slate-800 flex items-center justify-center px-4">
      <div className="w-full max-w-md bg-white dark:bg-slate-800 rounded-2xl shadow-lg p-8 text-center" data-tid="check-email-card">
        <Mail className="mx-auto mb-4 text-teal-600" size={40} aria-hidden="true" />
        <h1 className="text-xl font-bold text-slate-800 dark:text-slate-100 mb-2">{t('verify:check.title')}</h1>
        {given ? (
          <p className="text-slate-600 dark:text-slate-300" data-tid="check-email-sent">
            {t('verify:check.sent', { email: given })}
          </p>
        ) : (
          <>
            <p className="text-slate-600 dark:text-slate-300">{t('verify:check.sentNoEmail')}</p>
            <input
              type="email"
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              placeholder={t('verify:email.placeholder')}
              aria-label={t('verify:email.label')}
              data-tid="check-email-input"
              className="mt-3 w-full rounded-lg border border-slate-300 dark:border-slate-600 dark:bg-slate-700 dark:text-slate-100 px-3 py-2"
            />
          </>
        )}
        <p className="text-sm text-slate-500 dark:text-slate-400 mt-3">{t('verify:check.mailHint')}</p>

        <button
          type="button"
          onClick={resend}
          disabled={!email || busy || cooldown > 0}
          data-tid="check-email-resend"
          className="mt-5 w-full rounded-lg bg-teal-600 text-white py-2 font-medium disabled:opacity-50"
        >
          {cooldown > 0 ? t('verify:check.resendIn', { seconds: cooldown }) : t('verify:check.resend')}
        </button>
        {sent && <p role="status" className="mt-3 text-sm text-teal-700 dark:text-teal-300" data-tid="check-email-resent">{t('verify:check.resent')}</p>}
        {error && <p role="alert" className="mt-3 text-sm text-red-600 dark:text-red-400" data-tid="check-email-error">{error}</p>}

        <p className="mt-6 text-sm">
          <Link to="/login" className="text-teal-700 dark:text-teal-300 underline" data-tid="check-email-login">{t('verify:check.backToLogin')}</Link>
        </p>
      </div>
    </div>
  )
}
