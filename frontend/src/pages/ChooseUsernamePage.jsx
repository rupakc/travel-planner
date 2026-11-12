import { useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../context/AuthContext'
import { completeOAuthSignup } from '../services/authApi'
import { errorText } from '../services/apiError'
import { announceGame } from '../game/announce'
import { returnPathFrom } from '../utils/returnPath'
import { emit } from '../telemetry/client'

const field = 'w-full px-3 py-2.5 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-400 focus:border-teal-400'

// Second step of a first-time social sign-in. The exchange result arrives in
// router state; a reload loses it, so the visitor is sent back to start again.
export default function ChooseUsernamePage() {
  const { t } = useTranslation(['oauth', 'errors'])
  const { applySession } = useAuth()
  const location = useLocation()
  const navigate = useNavigate()
  const info = location.state?.oauth
  const [username, setUsername] = useState(info?.suggested_username || '')
  const [displayName, setDisplayName] = useState(info?.display_name || '')
  const [invite, setInvite] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const valid = !!info?.signup_token
  useEffect(() => {
    if (!valid) navigate('/login', { replace: true, state: { notice: t('oauth:startAgain') } })
  }, [valid, navigate, t])
  if (!valid) return null

  const submit = async (e) => {
    e.preventDefault()
    if (busy) return
    setError(''); setBusy(true)
    try {
      const body = { signup_token: info.signup_token, username: username.trim() }
      if (displayName.trim()) body.display_name = displayName.trim()
      if (info.invite_required) body.invite_code = invite.trim()
      const res = await completeOAuthSignup(body)
      await applySession(res.session)
      announceGame(res.game)
      emit('auth_result', { mode: 'signup', result: 'ok' })
      navigate(returnPathFrom({ search: `?next=${encodeURIComponent(info.return_to || '/')}` }), { replace: true })
    } catch (err) {
      emit('auth_result', { mode: 'signup', result: 'error', code: err?.code || undefined })
      setError(errorText(t, err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-teal-50 via-slate-50 to-sky-50 flex items-center justify-center px-4">
      <form onSubmit={submit} data-tid="oauth.username.form"
        className="w-full max-w-md bg-white rounded-3xl shadow-2xl ring-1 ring-gray-100 p-8 space-y-4">
        <h1 className="text-xl font-semibold text-gray-900">{t('oauth:username.title')}</h1>
        <p className="text-sm text-gray-600">{t('oauth:username.intro')}</p>
        {info.email && <p className="text-xs text-gray-500">{t('oauth:username.signedAs', { email: info.email })}</p>}
        {error && (
          <div role="alert" data-tid="oauth.username.error"
            className="p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">{error}</div>
        )}
        <div>
          <label htmlFor="oauth-username" className="block text-sm font-medium text-gray-700 mb-1">{t('oauth:username.username')}</label>
          <input id="oauth-username" data-tid="oauth.username.input" type="text" required autoFocus
            autoComplete="username" autoCapitalize="none" value={username}
            onChange={(e) => setUsername(e.target.value)} className={field} />
        </div>
        <div>
          <label htmlFor="oauth-display" className="block text-sm font-medium text-gray-700 mb-1">{t('oauth:username.displayName')}</label>
          <input id="oauth-display" data-tid="oauth.username.display-name" type="text" maxLength={60}
            value={displayName} onChange={(e) => setDisplayName(e.target.value)} className={field} />
        </div>
        {info.invite_required && (
          <div>
            <label htmlFor="oauth-invite" className="block text-sm font-medium text-gray-700 mb-1">{t('oauth:username.invite')}</label>
            <input id="oauth-invite" data-tid="oauth.username.invite" type="text" required
              value={invite} onChange={(e) => setInvite(e.target.value)} className={field} />
          </div>
        )}
        <button type="submit" disabled={busy} data-tid="oauth.username.submit"
          className="w-full py-2.5 bg-teal-700 hover:bg-teal-800 disabled:opacity-60 text-white font-medium rounded-lg text-sm">
          {busy ? t('oauth:username.submitting') : t('oauth:username.submit')}
        </button>
      </form>
    </div>
  )
}
