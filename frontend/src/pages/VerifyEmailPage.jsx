import { useEffect, useRef, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { MailCheck } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../context/AuthContext'
import { verifyEmail, resendVerification } from '../services/authApi'
import { errorText } from '../services/apiError'
import { announceGame } from '../game/announce'
import { emit } from '../telemetry/client'

const RESULT_BY_CODE = {
  token_expired: 'expired',
  token_invalid: 'invalid',
  token_used: 'used',
  email_changed: 'email_changed',
}

// Opening the link only reads the token; the single POST below is what consumes it.
export default function VerifyEmailPage() {
  const { t } = useTranslation(['verify', 'errors'])
  const { applySession } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  // Captured on first render: the URL is scrubbed before the POST, and
  // StrictMode re-runs the effect.
  const tokenRef = useRef(null)
  if (tokenRef.current === null) tokenRef.current = new URLSearchParams(location.search).get('token') || ''
  const startedRef = useRef(false)
  const [state, setState] = useState(tokenRef.current ? { status: 'working' } : { status: 'error', code: 'token_invalid' })

  useEffect(() => {
    if (startedRef.current || !tokenRef.current) return
    startedRef.current = true
    try {
      const url = new URL(window.location.href)
      url.searchParams.delete('token')
      window.history.replaceState(window.history.state, '', url.pathname + url.search + url.hash)
    } catch { /* non-browser environment */ }
    ;(async () => {
      let res
      try {
        res = await verifyEmail(tokenRef.current)
      } catch (err) {
        const code = err?.code
        emit('email_verify', { result: RESULT_BY_CODE[code] || 'invalid' })
        setState({ status: 'error', code, err })
        return
      }
      // The token is spent. Anything failing below must not look like an error.
      emit('email_verify', { result: 'ok' })
      let signedIn = false
      try {
        if (res?.session) {
          await applySession(res.session)
          signedIn = true
        }
        announceGame(res?.game)
      } catch { /* the email is confirmed regardless */ }
      if (signedIn) navigate('/', { replace: true })
      else setState({ status: 'confirmed', signIn: Boolean(res?.session) })
    })()
  }, [applySession, navigate])

  const shell = (children) => (
    <div className="min-h-screen bg-gradient-to-br from-teal-50 via-slate-50 to-sky-50 dark:from-slate-900 dark:via-slate-900 dark:to-slate-800 flex items-center justify-center px-4">
      <div className="w-full max-w-md bg-white dark:bg-slate-800 rounded-2xl shadow-lg p-8 text-center" data-tid="verify-card">
        <MailCheck className="mx-auto mb-4 text-teal-600" size={40} aria-hidden="true" />
        {children}
      </div>
    </div>
  )
  const link = 'text-teal-700 dark:text-teal-300 underline'

  if (state.status === 'working') {
    return shell(<p role="status" className="text-slate-600 dark:text-slate-300" data-tid="verify-working">{t('verify:verify.working')}</p>)
  }
  if (state.status === 'confirmed') {
    return shell(<>
      <h1 className="text-xl font-bold text-slate-800 dark:text-slate-100 mb-2" data-tid="verify-confirmed">{t('verify:verify.confirmed')}</h1>
      {state.signIn
        ? <Link to="/login" className={link} data-tid="verify-login-link">{t('verify:verify.signIn')}</Link>
        : <Link to="/account" className={link} data-tid="verify-account-link">{t('verify:verify.toAccount')}</Link>}
    </>)
  }
  const { code } = state
  if (code === 'token_used') {
    return shell(<>
      <h1 className="text-xl font-bold text-slate-800 dark:text-slate-100 mb-2" data-tid="verify-used">{t('verify:verify.used')}</h1>
      <Link to="/login" className={link} data-tid="verify-login-link">{t('verify:verify.signIn')}</Link>
    </>)
  }
  if (code === 'token_expired' || code === 'email_changed') {
    return shell(<ResendForm t={t} code={code} link={link} />)
  }
  if (code === 'token_invalid') {
    return shell(<>
      <h1 className="text-xl font-bold text-slate-800 dark:text-slate-100 mb-2" data-tid="verify-invalid">{t('verify:verify.invalid')}</h1>
      <Link to="/signup" className={link} data-tid="verify-signup-link">{t('verify:verify.toSignup')}</Link>
    </>)
  }
  return shell(<>
    <p role="alert" className="text-red-600 dark:text-red-400" data-tid="verify-error">{errorText(t, state.err)}</p>
    <Link to="/login" className={`${link} block mt-4`} data-tid="verify-login-link">{t('verify:verify.signIn')}</Link>
  </>)
}

function ResendForm({ t, code, link }) {
  const [email, setEmail] = useState('')
  const [busy, setBusy] = useState(false)
  const [sent, setSent] = useState(false)
  const [error, setError] = useState('')

  const submit = async (e) => {
    e.preventDefault()
    if (!email.trim() || busy) return
    setBusy(true)
    setError('')
    try {
      await resendVerification(email.trim())
      setSent(true)
      emit('email_verify', { result: 'resent' })
    } catch (err) {
      setError(errorText(t, err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <h1 className="text-xl font-bold text-slate-800 dark:text-slate-100 mb-2" data-tid="verify-expired">
        {code === 'email_changed' ? t('verify:verify.emailChanged') : t('verify:verify.expired')}
      </h1>
      {sent ? (
        <p role="status" className="text-teal-700 dark:text-teal-300" data-tid="verify-resent">{t('verify:verify.resent')}</p>
      ) : (
        <form onSubmit={submit} className="space-y-3 mt-3">
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder={t('verify:email.placeholder')}
            aria-label={t('verify:email.label')}
            data-tid="verify-email-input"
            className="w-full rounded-lg border border-slate-300 dark:border-slate-600 dark:bg-slate-700 dark:text-slate-100 px-3 py-2"
          />
          <button type="submit" disabled={busy || !email.trim()} data-tid="verify-resend" className="w-full rounded-lg bg-teal-600 text-white py-2 font-medium disabled:opacity-50">
            {t('verify:verify.resend')}
          </button>
          {error && <p role="alert" className="text-sm text-red-600 dark:text-red-400" data-tid="verify-resend-error">{error}</p>}
        </form>
      )}
      <Link to="/login" className={`${link} block mt-4`} data-tid="verify-login-link">{t('verify:verify.signIn')}</Link>
    </>
  )
}
