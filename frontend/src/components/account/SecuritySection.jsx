import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext'
import { getAuthProviders } from '../../services/api'
import { getLinkStartUrl, logoutAll, changePasswordV2 } from '../../services/authApi'
import { unlinkIdentity, requestEmailVerification } from '../../services/accountApi'
import { errorText } from '../../services/apiError'
import { navigateTo } from '../auth/navigate'
import { safeAuthStart } from '../../utils/navigate'
import PasswordStrengthMeter from '../auth/PasswordStrengthMeter'

// Provider order follows the contract. Brand names are not translated.
const PROVIDERS = [
  { id: 'apple', name: 'Apple' },
  { id: 'google', name: 'Google' },
  { id: 'facebook', name: 'Facebook' },
  { id: 'github', name: 'GitHub' },
]

const btn = 'px-3 py-1.5 rounded-lg text-sm font-medium border transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400 disabled:opacity-50'
const btnPlain = `${btn} border-slate-300 text-slate-700 hover:bg-slate-50`
const btnPrimary = `${btn} border-teal-600 bg-teal-600 text-white hover:bg-teal-700`
const input = 'w-full px-3 py-2 border border-slate-300 rounded-lg text-sm bg-white text-slate-900 focus:outline-none focus:ring-2 focus:ring-teal-400'

export default function SecuritySection({ account, reload }) {
  const { t } = useTranslation(['security', 'errors'])
  const { token, logout, updateTokenAfterPasswordChange } = useAuth()
  const navigate = useNavigate()
  const [providers, setProviders] = useState({})
  const [busy, setBusy] = useState(null)
  const [providerMsg, setProviderMsg] = useState(null) // {kind:'error'|'soon', text}
  const [verifyMsg, setVerifyMsg] = useState(null)
  const [pw, setPw] = useState({ current: '', next: '' })
  const [pwMsg, setPwMsg] = useState(null)
  const [confirmAll, setConfirmAll] = useState(false)
  const [allErr, setAllErr] = useState(null)

  useEffect(() => {
    let alive = true
    getAuthProviders()
      .then((list) => {
        if (!alive || !Array.isArray(list)) return
        setProviders(Object.fromEntries(list.map((p) => [p?.id, p])))
      })
      .catch(() => {})
    return () => { alive = false }
  }, [])

  if (!account) return null
  const user = account.user || {}
  const identities = Array.isArray(account.identities) ? account.identities : []
  const linked = Object.fromEntries(identities.map((i) => [i.provider, i]))
  const hasPassword = user.has_password !== false

  const connect = async (p) => {
    setProviderMsg(null)
    if (!providers[p.id]?.configured) {
      setProviderMsg({ kind: 'soon', text: t('security:providers.comingSoon', { provider: p.name }) })
      return
    }
    setBusy(p.id)
    try {
      const res = await getLinkStartUrl(token, p.id)
      const start = safeAuthStart(res?.start_url)
      if (!start) {
        setProviderMsg({ kind: 'error', text: t('errors:provider_unavailable') })
      } else {
        navigateTo(start)
      }
    } catch (err) {
      setProviderMsg({ kind: 'error', text: errorText(t, err) })
    } finally {
      setBusy(null)
    }
  }

  const disconnect = async (p) => {
    setProviderMsg(null)
    setBusy(p.id)
    try {
      await unlinkIdentity(token, p.id)
      await reload?.()
    } catch (err) {
      const text = err?.code === 'last_sign_in_method'
        ? t('security:providers.setPasswordFirst')
        : errorText(t, err)
      setProviderMsg({ kind: 'error', text })
    } finally {
      setBusy(null)
    }
  }

  const sendVerify = async () => {
    setVerifyMsg(null)
    setBusy('verify')
    try {
      await requestEmailVerification(token)
      setVerifyMsg({ kind: 'ok', text: t('security:email.sent', { email: user.email }) })
    } catch (err) {
      if (err?.code === 'already_verified') await reload?.()
      else setVerifyMsg({ kind: 'error', text: errorText(t, err) })
    } finally {
      setBusy(null)
    }
  }

  const submitPassword = async (e) => {
    e.preventDefault()
    setPwMsg(null)
    setBusy('password')
    try {
      const res = await changePasswordV2(token, hasPassword ? pw.current : '', pw.next)
      // The new token re-triggers AccountPage's load (it depends on the token);
      // calling reload now would still use the old, revoked token and 401.
      if (res?.access_token) updateTokenAfterPasswordChange(res.access_token)
      else await reload?.()
      setPw({ current: '', next: '' })
      setPwMsg({ kind: 'ok', text: hasPassword ? t('security:password.changed') : t('security:password.set') })
    } catch (err) {
      setPwMsg({ kind: 'error', text: errorText(t, err) })
    } finally {
      setBusy(null)
    }
  }

  const signOutEverywhere = async () => {
    setAllErr(null)
    setBusy('all')
    try {
      await logoutAll(token)
      logout()
      navigate('/login')
    } catch (err) {
      setAllErr(errorText(t, err))
      setBusy(null)
    }
  }

  const msgCls = (kind) => (kind === 'error'
    ? 'text-red-700'
    : 'text-slate-700')

  return (
    <section data-tid="security.section" aria-labelledby="security-title"
      className="bg-white rounded-2xl shadow p-6 space-y-6">
      <h2 id="security-title" className="text-lg font-bold text-slate-800">
        {t('security:title')}
      </h2>

      <div>
        <h3 className="text-sm font-semibold text-slate-800 mb-2">{t('security:providers.title')}</h3>
        <ul className="divide-y divide-slate-200">
          {PROVIDERS.map((p) => {
            const identity = linked[p.id]
            return (
              <li key={p.id} data-tid={`security.provider.${p.id}`} className="flex items-center justify-between gap-3 py-2">
                <div className="min-w-0">
                  <p className="text-sm font-medium text-slate-800">{p.name}</p>
                  <p className="text-xs text-slate-600 truncate">
                    {identity
                      ? (identity.email
                        ? t('security:providers.connectedAs', { email: identity.email })
                        : t('security:providers.connected'))
                      : (providers[p.id]?.configured ? t('security:providers.notConnected') : t('security:providers.soon'))}
                  </p>
                </div>
                {identity ? (
                  <button type="button" className={btnPlain} disabled={busy === p.id}
                    data-tid={`security.disconnect.${p.id}`} onClick={() => disconnect(p)}>
                    {t('security:providers.disconnect')}
                  </button>
                ) : (
                  <button type="button" className={btnPlain} disabled={busy === p.id}
                    data-tid={`security.connect.${p.id}`} onClick={() => connect(p)}>
                    {t('security:providers.connect')}
                  </button>
                )}
              </li>
            )
          })}
        </ul>
        <div aria-live="polite">
          {providerMsg && (
            <p data-tid="security.provider-msg" className={`mt-2 text-sm ${msgCls(providerMsg.kind)}`}>{providerMsg.text}</p>
          )}
        </div>
      </div>

      {user.email && user.email_verified === false && (
        <div data-tid="security.email">
          <h3 className="text-sm font-semibold text-slate-800 mb-1">{t('security:email.title')}</h3>
          <p className="text-sm text-slate-700 mb-2">{t('security:email.unverified', { email: user.email })}</p>
          <button type="button" className={btnPlain} disabled={busy === 'verify'}
            data-tid="security.verify-email" onClick={sendVerify}>
            {t('security:email.verify')}
          </button>
          <div aria-live="polite">
            {verifyMsg && <p data-tid="security.verify-msg" className={`mt-2 text-sm ${msgCls(verifyMsg.kind)}`}>{verifyMsg.text}</p>}
          </div>
        </div>
      )}

      <form onSubmit={submitPassword} data-tid="security.password-form" className="space-y-3">
        <h3 className="text-sm font-semibold text-slate-800">
          {hasPassword ? t('security:password.changeTitle') : t('security:password.setTitle')}
        </h3>
        {hasPassword && (
          <label className="block text-sm text-slate-700">
            {t('security:password.current')}
            <input type="password" autoComplete="current-password" className={`${input} mt-1`}
              data-tid="security.current-password" value={pw.current}
              onChange={(e) => setPw((s) => ({ ...s, current: e.target.value }))} />
          </label>
        )}
        <label className="block text-sm text-slate-700">
          {t('security:password.new')}
          <input type="password" autoComplete="new-password" className={`${input} mt-1`}
            data-tid="security.new-password" value={pw.next}
            onChange={(e) => setPw((s) => ({ ...s, next: e.target.value }))} />
        </label>
        <PasswordStrengthMeter password={pw.next} username={user.username}
          email={user.email} />
        <button type="submit" className={btnPrimary} data-tid="security.password-save"
          disabled={busy === 'password' || !pw.next || (hasPassword && !pw.current)}>
          {hasPassword ? t('security:password.change') : t('security:password.setButton')}
        </button>
        <div aria-live="polite">
          {pwMsg && <p data-tid="security.password-msg" className={`text-sm ${msgCls(pwMsg.kind)}`}>{pwMsg.text}</p>}
        </div>
      </form>

      <div data-tid="security.sessions">
        <h3 className="text-sm font-semibold text-slate-800 mb-1">{t('security:sessions.title')}</h3>
        <p className="text-sm text-slate-700 mb-2">{t('security:sessions.body')}</p>
        {confirmAll ? (
          <div role="alertdialog" aria-label={t('security:sessions.confirm')} className="space-y-2">
            <p className="text-sm text-slate-800">{t('security:sessions.confirm')}</p>
            <div className="flex gap-2">
              <button type="button" className={`${btn} border-red-600 bg-red-600 text-white hover:bg-red-700`}
                disabled={busy === 'all'} data-tid="security.logout-all-confirm" onClick={signOutEverywhere}>
                {t('security:sessions.confirmYes')}
              </button>
              <button type="button" className={btnPlain} data-tid="security.logout-all-cancel"
                onClick={() => setConfirmAll(false)}>
                {t('security:sessions.cancel')}
              </button>
            </div>
          </div>
        ) : (
          <button type="button" className={btnPlain} data-tid="security.logout-all"
            onClick={() => setConfirmAll(true)}>
            {t('security:sessions.signOutAll')}
          </button>
        )}
        <div aria-live="polite">
          {allErr && <p data-tid="security.logout-all-msg" className="mt-2 text-sm text-red-700">{allErr}</p>}
        </div>
      </div>
    </section>
  )
}
