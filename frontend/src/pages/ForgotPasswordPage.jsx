import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Plane, Mail } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { requestPasswordReset } from '../services/authApi'
import { errorText } from '../services/apiError'
import { useClientConfig, resetAvailable } from '../hooks/useClientConfig'
import { emit } from '../telemetry/client'
import AttributionFooter from '../components/ui/AttributionFooter'

export default function ForgotPasswordPage() {
  const { t } = useTranslation('recovery')
  const { t: tc } = useTranslation()
  const { config, loaded } = useClientConfig()
  const [email, setEmail] = useState('')
  const [loading, setLoading] = useState(false)
  const [sent, setSent] = useState(false)
  const [error, setError] = useState('')

  const unavailable = loaded && !resetAvailable(config)

  const submit = async (e) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await requestPasswordReset(email.trim())
      emit('password_reset', { step: 'request', result: 'ok' })
      setSent(true)
    } catch (err) {
      emit('password_reset', { step: 'request', result: 'error' })
      // Only 429 / 503 are shown; any other outcome reads like success so the
      // page never reveals whether an account exists.
      if (err?.status === 429 || err?.status === 503) setError(errorText(tc, err))
      else setSent(true)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-teal-50 via-slate-50 to-sky-50 dark:from-gray-900 dark:via-gray-900 dark:to-gray-900 flex items-center justify-center px-4">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 bg-gradient-to-br from-teal-500 to-teal-700 rounded-2xl shadow-lg mb-4">
            <Plane size={32} className="text-white" />
          </div>
        </div>
        <div className="bg-white dark:bg-gray-800 rounded-3xl shadow-2xl ring-1 ring-gray-100 dark:ring-gray-700 p-8">
          <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100 mb-2">{t('forgot.title')}</h1>
          {unavailable ? (
            <p role="alert" data-tid="forgot.unavailable" className="text-sm text-gray-600 dark:text-gray-300">
              {t('forgot.unavailable')}
            </p>
          ) : sent ? (
            <p role="status" data-tid="forgot.sent" className="text-sm text-gray-700 dark:text-gray-200">
              {t('forgot.sent')}
            </p>
          ) : (
            <form onSubmit={submit} className="space-y-4">
              <p className="text-sm text-gray-500 dark:text-gray-400">{t('forgot.intro')}</p>
              {error && (
                <div role="alert" data-tid="forgot.error"
                  className="p-3 bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 rounded-lg text-sm text-red-700 dark:text-red-300">
                  {error}
                </div>
              )}
              <div>
                <label htmlFor="forgot-email" className="block text-sm font-medium text-gray-700 dark:text-gray-200 mb-1">
                  {t('forgot.email')}
                </label>
                <div className="relative">
                  <input id="forgot-email" type="email" required autoFocus autoComplete="email" data-tid="forgot.email"
                    value={email} onChange={(e) => setEmail(e.target.value)}
                    className="w-full pl-9 pr-3 py-2.5 border border-gray-300 dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100 rounded-lg focus:outline-none focus:ring-2 focus:ring-teal-400 text-sm" />
                  <Mail size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
                </div>
              </div>
              <button type="submit" disabled={loading} data-tid="forgot.submit"
                className="w-full py-3 bg-gradient-to-r from-teal-600 to-teal-700 text-white font-semibold rounded-xl shadow-lg disabled:opacity-60 text-sm">
                {loading ? t('forgot.sending') : t('forgot.submit')}
              </button>
            </form>
          )}
          <p className="mt-6 text-center text-sm">
            <Link to="/login" data-tid="forgot.back" className="text-teal-600 dark:text-teal-400 hover:underline">
              {t('forgot.back')}
            </Link>
          </p>
        </div>
        <AttributionFooter />
      </div>
    </div>
  )
}
