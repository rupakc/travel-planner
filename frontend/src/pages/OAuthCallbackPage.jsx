import { useEffect, useRef } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../context/AuthContext'
import { exchangeOAuthCode } from '../services/authApi'
import { errorText } from '../services/apiError'
import { announceGame } from '../game/announce'
import { returnPathFrom } from '../utils/returnPath'
import { emit } from '../telemetry/client'

const METHOD_KEY = 'tp_oauth_method'

function startedMethod() {
  try { return sessionStorage.getItem(METHOD_KEY) || undefined } catch { return undefined }
}

// Re-validates the server's return_to: same-origin paths only, else home.
const safePath = (raw) =>
  returnPathFrom({ search: `?next=${encodeURIComponent(typeof raw === 'string' ? raw : '/')}` })

// Where the provider (via the API) sends the browser back: `?error=<code>` or
// `?code=<handoff>`. The code is removed from the address bar before the
// exchange; a needs_username result travels in router state, never the URL.
export default function OAuthCallbackPage() {
  const { t } = useTranslation(['oauth', 'errors'])
  const { applySession } = useAuth()
  const location = useLocation()
  const navigate = useNavigate()
  const started = useRef(false)

  useEffect(() => {
    if (started.current) return
    started.current = true
    const q = new URLSearchParams(location.search)
    const error = q.get('error')
    const code = q.get('code')
    const method = startedMethod()
    const toLogin = (notice, errCode) => {
      emit('auth_result', { method, mode: 'signin', result: errCode === 'cancelled' ? 'cancelled' : 'error', code: errCode })
      navigate('/login', { replace: true, state: { notice, notice_code: errCode } })
    }

    if (error) {
      const text = error === 'email_in_use_unverified'
        ? t('oauth:emailInUseUnverified')
        : errorText(t, { code: error })
      toLogin(text, error)
      return
    }
    if (!code) { toLogin(t('oauth:startAgain'), 'bad_request'); return }

    window.history.replaceState(null, '', location.pathname)
    exchangeOAuthCode(code).then(async (res) => {
      if (res?.status === 'signed_in') {
        await applySession(res.session)
        announceGame(res.game)
        emit('auth_result', { method, mode: 'signin', result: 'ok' })
        navigate(safePath(res.return_to), { replace: true })
      } else if (res?.status === 'needs_username') {
        emit('auth_result', { method, mode: 'signup', result: 'needs_username' })
        navigate('/auth/username', { replace: true, state: { oauth: res } })
      } else if (res?.status === 'linked') {
        emit('auth_result', { method: res.provider, mode: 'link', result: 'ok' })
        navigate(safePath(res.return_to || '/account'), { replace: true, state: { toast: t('oauth:linked') } })
      } else {
        toLogin(t('errors:generic'), 'bad_request')
      }
    }).catch((err) => toLogin(errorText(t, err), err?.code || 'error'))
  }, [])

  return (
    <div className="min-h-screen flex items-center justify-center px-4">
      <p role="status" data-tid="oauth.working" className="text-sm text-slate-600 dark:text-slate-300">
        {t('oauth:working')}
      </p>
    </div>
  )
}
