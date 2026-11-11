import { useState } from 'react'
import { useNavigate, useLocation, Link } from 'react-router-dom'
import { Plane, Lock, User, Eye, EyeOff } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../context/AuthContext'
import { returnPathFrom } from '../utils/returnPath'
import { useClientConfig, signupAvailable, resetAvailable } from '../hooks/useClientConfig'
import { resendVerification } from '../services/authApi'
import { errorText } from '../services/apiError'
import SocialSignInButtons from '../components/auth/SocialSignInButtons'
import AttributionFooter from '../components/ui/AttributionFooter'

export default function LoginPage() {
  const { t } = useTranslation('account')
  const { t: tAuth } = useTranslation('auth')
  const { t: tSignup } = useTranslation('signup')
  const { t: tAll } = useTranslation()
  const { config } = useClientConfig()
  const { login } = useAuth()
  const navigate   = useNavigate()
  const location   = useLocation()
  const from       = returnPathFrom(location)  // same-origin only

  const [form, setForm]     = useState({ username: '', password: '' })
  const [showPw, setShowPw] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError]   = useState('')
  const [pending, setPending] = useState(null)   // {hint} after 403 account_pending
  const [resendEmail, setResendEmail] = useState('')
  const [resendState, setResendState] = useState('idle')  // idle | sending | sent
  const [resendError, setResendError] = useState('')

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    setPending(null)
    setResendState('idle')
    setResendError('')
    setLoading(true)
    try {
      await login(form.username, form.password)
      navigate(from, { replace: true })
    } catch (err) {
      if (err.code === 'account_pending') {
        setPending({ hint: err.extra?.email_hint || '' })
        setResendEmail(form.username.includes('@') ? form.username.trim() : '')
        return
      }
      setError(err.message || t('login.failed'))
    } finally {
      setLoading(false)
    }
  }

  const handleResend = async () => {
    setResendState('sending')
    setResendError('')
    try {
      await resendVerification(resendEmail.trim())
      setResendState('sent')
    } catch (err) {
      setResendState('idle')
      setResendError(errorText(tAll, err))
    }
  }

  const accountsOn = !!config?.auth
  const showSignup = signupAvailable(config)
  const showReset = resetAvailable(config)

  return (
    <div className="min-h-screen bg-gradient-to-br from-teal-50 via-slate-50 to-sky-50 flex items-center justify-center px-4">
      <div className="w-full max-w-md">
        {/* Logo */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 bg-gradient-to-br from-teal-500 to-teal-700 rounded-2xl shadow-lg mb-4">
            <Plane size={32} className="text-white" />
          </div>
          <h1 className="font-display text-3xl font-bold text-slate-800 tracking-tight">Travel Planner</h1>
          <p className="text-slate-500 mt-1">{t('login.tagline')}</p>
        </div>

        {/* Card */}
        <div className="bg-white rounded-3xl shadow-2xl ring-1 ring-gray-100 p-8">
          <h2 className="text-xl font-semibold text-gray-900 mb-6">{t('login.title')}</h2>

          {error && (
            <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
              {error}
            </div>
          )}

          {pending && (
            <div role="status" data-tid="login.pending" className="mb-4 p-3 bg-amber-50 border border-amber-200 rounded-lg text-sm text-amber-800 dark:bg-amber-950 dark:border-amber-900 dark:text-amber-200">
              <p className="font-medium">{tSignup('login.pendingTitle')}</p>
              <p className="mt-1">{pending.hint
                ? tSignup('login.pendingBody', { hint: pending.hint })
                : tSignup('login.pendingNoHint')}</p>
              {resendState === 'sent' ? (
                <p data-tid="login.resent" className="mt-2 font-medium">{tSignup('login.resent')}</p>
              ) : (
                <div className="mt-2 space-y-2">
                  {!form.username.includes('@') && (
                    <input type="email" data-tid="login.resend-email" value={resendEmail}
                      onChange={e => setResendEmail(e.target.value)}
                      placeholder={tSignup('login.resendEmail')} aria-label={tSignup('login.resendEmail')}
                      className="w-full px-3 py-2 border border-amber-300 rounded-lg text-sm text-gray-900 dark:bg-gray-800 dark:text-gray-100 dark:border-amber-800" />
                  )}
                  <button type="button" onClick={handleResend} data-tid="login.resend"
                    disabled={resendState === 'sending' || !resendEmail.trim()}
                    className="px-3 py-1.5 rounded-lg bg-amber-600 text-white text-sm font-medium hover:bg-amber-700 disabled:opacity-60">
                    {resendState === 'sending' ? tSignup('login.resending') : tSignup('login.resend')}
                  </button>
                  {resendError && <p role="alert" className="text-red-700 dark:text-red-300">{resendError}</p>}
                </div>
              )}
            </div>
          )}

          <SocialSignInButtons mode="signin" />

          <div className="flex items-center gap-3 my-5" role="separator">
            <span className="flex-1 h-px bg-gray-200 dark:bg-gray-700" />
            <span className="text-xs uppercase tracking-wide text-gray-400">{tAuth('divider')}</span>
            <span className="flex-1 h-px bg-gray-200 dark:bg-gray-700" />
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">{accountsOn ? tSignup('login.identifier') : t('login.username')}</label>
              <div className="relative">
                <input
                  type="text" required autoFocus data-tid="login.username"
                  value={form.username}
                  onChange={e => setForm(f => ({ ...f, username: e.target.value }))}
                  placeholder={accountsOn ? tSignup('login.identifierPlaceholder') : t('login.usernamePlaceholder')}
                  className="w-full pl-9 pr-3 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-teal-400 focus:border-teal-400 text-sm"
                />
                <User size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">{t('login.password')}</label>
              <div className="relative">
                <input
                  type={showPw ? 'text' : 'password'} required data-tid="login.password"
                  value={form.password}
                  onChange={e => setForm(f => ({ ...f, password: e.target.value }))}
                  placeholder={t('login.passwordPlaceholder')}
                  className="w-full pl-9 pr-10 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-teal-400 focus:border-teal-400 text-sm"
                />
                <Lock size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
                <button type="button" onClick={() => setShowPw(v => !v)}
                  data-tid="login.toggle-password"
                  aria-label={showPw ? t('login.hidePassword') : t('login.showPassword')}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600">
                  {showPw ? <EyeOff size={14} /> : <Eye size={14} />}
                </button>
              </div>
            </div>

            <button type="submit" disabled={loading} data-tid="login.submit"
              className="w-full py-3 bg-gradient-to-r from-teal-600 to-teal-700 text-white font-semibold rounded-xl shadow-lg hover:from-teal-700 hover:to-teal-800 active:scale-[0.99] disabled:opacity-60 transition-all text-sm">
              {loading ? t('login.submitting') : t('login.submit')}
            </button>
          </form>

          {(showSignup || showReset) && (
            <div className="mt-5 flex items-center justify-between text-sm">
              {showSignup && (
                <Link to="/signup" data-tid="login.create-account" className="font-medium text-teal-700 dark:text-teal-400 hover:underline">{tSignup('login.createAccount')}</Link>
              )}
              {showReset && (
                <Link to="/forgot-password" data-tid="login.forgot" className="text-gray-600 dark:text-gray-400 hover:underline ml-auto">{tSignup('login.forgot')}</Link>
              )}
            </div>
          )}
        </div>
        <AttributionFooter />
      </div>
    </div>
  )
}
