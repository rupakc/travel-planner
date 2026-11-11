import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { Plane, Lock } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { confirmPasswordReset } from '../services/authApi'
import { errorText } from '../services/apiError'
import { useAuth } from '../context/AuthContext'
import { emit } from '../telemetry/client'
import PasswordStrengthMeter from '../components/auth/PasswordStrengthMeter'
import AttributionFooter from '../components/ui/AttributionFooter'

const TOKEN_RESULT = { token_expired: 'expired', token_used: 'used', token_invalid: 'invalid' }
const INPUT = 'w-full pl-9 pr-3 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-teal-400 text-sm'

export default function ResetPasswordPage() {
  const { t } = useTranslation('recovery')
  const { t: tc } = useTranslation()
  const { applySession } = useAuth()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  // Read the token once, then take it out of the address bar and history.
  const tokenRef = useRef(params.get('token') || '')
  const token = tokenRef.current

  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null) // {code, text}
  const [done, setDone] = useState(false)
  const [sessionFailed, setSessionFailed] = useState(false)

  useEffect(() => {
    if (window.location.search.includes('token')) {
      window.history.replaceState(window.history.state, '', window.location.pathname)
    }
  }, [])

  const mismatch = confirm !== '' && confirm !== password
  const fieldError = error && /^password_/.test(error.code || '') ? error.text : ''
  const tokenProblem = !token || (error && TOKEN_RESULT[error.code])

  const submit = async (e) => {
    e.preventDefault()
    if (password !== confirm) return
    setError(null)
    setLoading(true)
    try {
      const res = await confirmPasswordReset(token, password)
      emit('password_reset', { step: 'confirm', result: 'ok' })
      setDone(true)
      // The password is already changed: a failed sign-in must not look like a failed reset.
      try { await applySession(res.session) } catch { setSessionFailed(true) }
    } catch (err) {
      emit('password_reset', { step: 'confirm', result: TOKEN_RESULT[err?.code] || 'error' })
      setError({ code: err?.code, text: errorText(tc, err) })
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-teal-50 via-slate-50 to-sky-50 flex items-center justify-center px-4">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 bg-gradient-to-br from-teal-500 to-teal-700 rounded-2xl shadow-lg mb-4">
            <Plane size={32} className="text-white" />
          </div>
        </div>
        <div className="bg-white rounded-3xl shadow-2xl ring-1 ring-gray-100 p-8">
          <h1 className="text-xl font-semibold text-gray-900 mb-4">{t('reset.title')}</h1>
          {done ? (
            <div className="space-y-4">
              <p role="status" data-tid="reset.done" className="text-sm text-gray-700">{t('reset.done')}</p>
              <button type="button" data-tid="reset.continue" onClick={() => navigate(sessionFailed ? '/login' : '/', { replace: true })}
                className="w-full py-3 bg-gradient-to-r from-teal-600 to-teal-700 text-white font-semibold rounded-xl shadow-lg text-sm">
                {t('reset.continue')}
              </button>
            </div>
          ) : tokenProblem ? (
            <div role="alert" data-tid="reset.token-problem" className="space-y-3 text-sm text-gray-700">
              <p>{error?.text || t('reset.missingToken')}</p>
              <Link to="/forgot-password" data-tid="reset.request-new" className="text-teal-600 hover:underline">
                {t('reset.requestNew')}
              </Link>
            </div>
          ) : (
            <form onSubmit={submit} className="space-y-4" noValidate>
              {error && !fieldError && (
                <div role="alert" data-tid="reset.error"
                  className="p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
                  {error.text}
                </div>
              )}
              <div>
                <label htmlFor="reset-password" className="block text-sm font-medium text-gray-700 mb-1">{t('reset.password')}</label>
                <div className="relative">
                  <input id="reset-password" type="password" required autoFocus autoComplete="new-password" data-tid="reset.password"
                    value={password} onChange={(e) => setPassword(e.target.value)} className={INPUT} />
                  <Lock size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
                </div>
                <PasswordStrengthMeter password={password} />
                {fieldError && (
                  <p role="alert" data-tid="reset.password-error" className="mt-1 text-xs text-red-600">{fieldError}</p>
                )}
              </div>
              <div>
                <label htmlFor="reset-confirm" className="block text-sm font-medium text-gray-700 mb-1">{t('reset.confirm')}</label>
                <div className="relative">
                  <input id="reset-confirm" type="password" required autoComplete="new-password" data-tid="reset.confirm"
                    value={confirm} onChange={(e) => setConfirm(e.target.value)}
                    aria-invalid={mismatch} className={INPUT} />
                  <Lock size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
                </div>
                {mismatch && (
                  <p role="alert" data-tid="reset.mismatch" className="mt-1 text-xs text-red-600">{t('reset.mismatch')}</p>
                )}
              </div>
              <button type="submit" disabled={loading || !password || mismatch || confirm !== password} data-tid="reset.submit"
                className="w-full py-3 bg-gradient-to-r from-teal-600 to-teal-700 text-white font-semibold rounded-xl shadow-lg disabled:opacity-60 text-sm">
                {loading ? t('reset.saving') : t('reset.submit')}
              </button>
            </form>
          )}
        </div>
        <AttributionFooter />
      </div>
    </div>
  )
}
