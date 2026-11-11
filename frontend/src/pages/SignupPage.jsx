import { useEffect, useState } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { Plane, Lock, User, Mail, Eye, EyeOff } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../context/AuthContext'
import { useClientConfig, signupAvailable } from '../hooks/useClientConfig'
import { signup } from '../services/authApi'
import { errorText } from '../services/apiError'
import { emit } from '../telemetry/client'
import SocialSignInButtons from '../components/auth/SocialSignInButtons'
import PasswordStrengthMeter from '../components/auth/PasswordStrengthMeter'
import AttributionFooter from '../components/ui/AttributionFooter'

const USERNAME_RE = /^[a-z0-9_]{3,20}$/
const FIELD_OF = {
  username_taken: 'username', username_invalid: 'username', username_reserved: 'username',
  email_invalid: 'email',
  password_too_short: 'password', password_too_long: 'password', password_common: 'password',
  password_matches_identity: 'password',
  display_name_invalid: 'displayName',
  invite_required: 'invite', invite_invalid: 'invite',
}
const INPUT = 'w-full py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-teal-400 focus:border-teal-400 text-sm dark:bg-gray-800 dark:border-gray-600 dark:text-gray-100'
const FIELD_ERR = 'mt-1 text-xs text-red-600 dark:text-red-400'

export default function SignupPage() {
  const { t } = useTranslation('signup')
  const { t: tAuth } = useTranslation('auth')
  const { t: tAll } = useTranslation()
  const { isAuthenticated } = useAuth()
  const navigate = useNavigate()
  const { config, loaded } = useClientConfig()
  const inviteMode = config?.auth?.signup_mode === 'invite'

  const [form, setForm] = useState({ username: '', email: '', password: '', displayName: '', invite: '' })
  const [showPw, setShowPw] = useState(false)
  const [loading, setLoading] = useState(false)
  const [errors, setErrors] = useState({})

  const available = signupAvailable(config)
  useEffect(() => { if (available) emit('signup_step', { step: 'form' }) }, [available])

  if (isAuthenticated) return <Navigate to="/" replace />
  if (loaded && !available) return <Navigate to="/login" replace />

  const set = (key) => (e) => {
    const value = key === 'username' ? e.target.value.toLowerCase() : e.target.value
    setForm((f) => ({ ...f, [key]: value }))
    setErrors((er) => (er[key] || er.form ? { ...er, [key]: undefined, form: undefined } : er))
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    const username = form.username.trim().toLowerCase()
    const email = form.email.trim()
    if (!USERNAME_RE.test(username)) {
      setErrors({ username: tAll('errors:username_invalid') })
      return
    }
    setErrors({})
    setLoading(true)
    emit('auth_start', { method: 'password', mode: 'signup' })
    try {
      const body = { username, email, password: form.password }
      if (form.displayName.trim()) body.display_name = form.displayName.trim()
      if (inviteMode && form.invite.trim()) body.invite_code = form.invite.trim()
      const res = await signup(body)
      emit('auth_result', { method: 'password', mode: 'signup', result: 'pending' })
      emit('signup_step', { step: 'check_email' })
      // Router state, not the URL: the address stays out of history and referrers
      // (history.state survives a reload; without it the page asks for the address).
      navigate('/check-email', { state: { email: res?.email || email.toLowerCase() } })
    } catch (err) {
      emit('auth_result', { method: 'password', mode: 'signup', result: 'error', code: err?.code || 'unknown' })
      const field = FIELD_OF[err?.code]
      const text = errorText(tAll, err)
      setErrors(field ? { [field]: text } : { form: text })
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-teal-50 via-slate-50 to-sky-50 dark:from-gray-900 dark:via-gray-900 dark:to-gray-800 flex items-center justify-center px-4 py-8">
      <div className="w-full max-w-md">
        <div className="text-center mb-6">
          <div className="inline-flex items-center justify-center w-16 h-16 bg-gradient-to-br from-teal-500 to-teal-700 rounded-2xl shadow-lg mb-4">
            <Plane size={32} className="text-white" />
          </div>
          <h1 className="font-display text-3xl font-bold text-slate-800 dark:text-gray-100 tracking-tight">Travel Planner</h1>
          <p className="text-slate-500 dark:text-gray-400 mt-1">{t('tagline')}</p>
        </div>

        <div className="bg-white dark:bg-gray-900 rounded-3xl shadow-2xl ring-1 ring-gray-100 dark:ring-gray-800 p-8">
          <h2 className="text-xl font-semibold text-gray-900 dark:text-gray-100 mb-6">{t('title')}</h2>

          {errors.form && (
            <div role="alert" data-tid="signup.error" className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700 dark:bg-red-950 dark:border-red-900 dark:text-red-300">
              {errors.form}
            </div>
          )}

          <SocialSignInButtons mode="signup" />

          <div className="flex items-center gap-3 my-5" role="separator">
            <span className="flex-1 h-px bg-gray-200 dark:bg-gray-700" />
            <span className="text-xs uppercase tracking-wide text-gray-400">{tAuth('divider')}</span>
            <span className="flex-1 h-px bg-gray-200 dark:bg-gray-700" />
          </div>

          <form onSubmit={handleSubmit} className="space-y-4" noValidate>
            <div>
              <label htmlFor="signup-username" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">{t('username.label')}</label>
              <div className="relative">
                <input id="signup-username" type="text" required autoFocus autoComplete="username"
                  autoCapitalize="none" autoCorrect="off" spellCheck={false} maxLength={20}
                  data-tid="signup.username" value={form.username} onChange={set('username')}
                  placeholder={t('username.placeholder')} aria-invalid={!!errors.username}
                  className={`${INPUT} pl-9 pr-3`} />
                <User size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
              </div>
              {errors.username
                ? <p role="alert" data-tid="signup.username-error" className={FIELD_ERR}>{errors.username}</p>
                : <p data-tid="signup.username-hint" className="mt-1 text-xs text-gray-500 dark:text-gray-400">{t('username.hint')}</p>}
            </div>

            <div>
              <label htmlFor="signup-email" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">{t('email.label')}</label>
              <div className="relative">
                <input id="signup-email" type="email" required autoComplete="email"
                  data-tid="signup.email" value={form.email} onChange={set('email')}
                  placeholder={t('email.placeholder')} aria-invalid={!!errors.email}
                  className={`${INPUT} pl-9 pr-3`} />
                <Mail size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
              </div>
              {errors.email && <p role="alert" data-tid="signup.email-error" className={FIELD_ERR}>{errors.email}</p>}
            </div>

            <div>
              <label htmlFor="signup-password" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">{t('password.label')}</label>
              <div className="relative">
                <input id="signup-password" type={showPw ? 'text' : 'password'} required autoComplete="new-password"
                  data-tid="signup.password" value={form.password} onChange={set('password')}
                  placeholder={t('password.placeholder')} aria-invalid={!!errors.password}
                  className={`${INPUT} pl-9 pr-10`} />
                <Lock size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
                <button type="button" onClick={() => setShowPw((v) => !v)} data-tid="signup.toggle-password"
                  aria-label={showPw ? t('password.hide') : t('password.show')}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600">
                  {showPw ? <EyeOff size={14} /> : <Eye size={14} />}
                </button>
              </div>
              <PasswordStrengthMeter password={form.password} username={form.username} email={form.email} />
              {errors.password && <p role="alert" data-tid="signup.password-error" className={FIELD_ERR}>{errors.password}</p>}
            </div>

            <div>
              <label htmlFor="signup-display-name" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">{t('displayName.label')}</label>
              <input id="signup-display-name" type="text" autoComplete="name" maxLength={50}
                data-tid="signup.display-name" value={form.displayName} onChange={set('displayName')}
                placeholder={t('displayName.placeholder')} aria-invalid={!!errors.displayName}
                className={`${INPUT} px-3`} />
              {errors.displayName && <p role="alert" data-tid="signup.display-name-error" className={FIELD_ERR}>{errors.displayName}</p>}
            </div>

            {inviteMode && (
              <div>
                <label htmlFor="signup-invite" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">{t('invite.label')}</label>
                <input id="signup-invite" type="text" required autoComplete="off" autoCapitalize="none"
                  data-tid="signup.invite" value={form.invite} onChange={set('invite')}
                  placeholder={t('invite.placeholder')} aria-invalid={!!errors.invite}
                  className={`${INPUT} px-3`} />
                {errors.invite && <p role="alert" data-tid="signup.invite-error" className={FIELD_ERR}>{errors.invite}</p>}
              </div>
            )}

            <button type="submit" disabled={loading || !loaded} data-tid="signup.submit"
              className="w-full py-3 bg-gradient-to-r from-teal-600 to-teal-700 text-white font-semibold rounded-xl shadow-lg hover:from-teal-700 hover:to-teal-800 active:scale-[0.99] disabled:opacity-60 transition-all text-sm">
              {loading ? t('submitting') : t('submit')}
            </button>
          </form>

          <p className="mt-5 text-center text-sm text-gray-600 dark:text-gray-400">
            {t('haveAccount')}{' '}
            <Link to="/login" data-tid="signup.signin-link" className="font-medium text-teal-700 dark:text-teal-400 hover:underline">{t('signIn')}</Link>
          </p>
        </div>
        <AttributionFooter />
      </div>
    </div>
  )
}
