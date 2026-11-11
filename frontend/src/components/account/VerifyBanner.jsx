import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../../context/AuthContext'
import { requestEmailVerification } from '../../services/accountApi'
import { errorText } from '../../services/apiError'
import { emit } from '../../telemetry/client'

const DISMISS_KEY = 'tp_verify_banner_dismissed'
const SHOWN_KEY = 'tp_verify_banner_shown'

const read = (k) => { try { return sessionStorage.getItem(k) === '1' } catch { return false } }
const write = (k) => { try { sessionStorage.setItem(k, '1') } catch { /* private mode */ } }

// Slim banner for signed-in users whose email is unconfirmed. An old backend
// sends no `account_verified`, which AuthContext treats as verified.
export default function VerifyBanner() {
  const { t } = useTranslation('quota')
  const { token, user, accountVerified } = useAuth()
  const [dismissed, setDismissed] = useState(() => read(DISMISS_KEY))
  const [state, setState] = useState({ phase: 'idle', error: '' })
  const show = !!user && accountVerified === false && !dismissed

  useEffect(() => {
    if (!show || read(SHOWN_KEY)) return
    write(SHOWN_KEY)
    emit('quota_block', { bucket: 'search', reason: 'unverified' })
  }, [show])

  if (!show) return null

  const send = async () => {
    if (state.phase === 'sending') return
    setState({ phase: 'sending', error: '' })
    try {
      await requestEmailVerification(token)
      setState({ phase: 'sent', error: '' })
    } catch (err) {
      setState({ phase: 'error', error: errorText(t, err) })
    }
  }

  return (
    <div
      role="status" data-tid="verify-banner"
      className="flex flex-wrap items-center justify-center gap-x-3 gap-y-1 px-4 py-2 text-sm bg-amber-100 text-amber-900"
    >
      <span data-tid="verify-banner.text">
        {state.phase === 'sent' ? t('banner.sent') : t('banner.text')}
      </span>
      {state.phase !== 'sent' && (
        <button
          type="button" data-tid="verify-banner.send" onClick={send} disabled={state.phase === 'sending'}
          className="font-semibold underline disabled:opacity-60"
        >
          {t('banner.send')}
        </button>
      )}
      {state.error && <span data-tid="verify-banner.error" className="text-red-700">{state.error}</span>}
      <button
        type="button" data-tid="verify-banner.dismiss" aria-label={t('banner.dismiss')}
        onClick={() => { write(DISMISS_KEY); setDismissed(true) }}
        className="ml-1 px-1"
      >
        ×
      </button>
    </div>
  )
}
