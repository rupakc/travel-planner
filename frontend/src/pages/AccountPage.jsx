import { Component, useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { getAccount } from '../services/accountApi'
import { useClientConfig, featureOn } from '../hooks/useClientConfig'
import ProfileSection from '../components/account/ProfileSection'
import SettingsSection from '../components/account/SettingsSection'
import SecuritySection from '../components/account/SecuritySection'
import QuotaSection from '../components/account/QuotaSection'
import GameSection from '../components/game/GameSection'
import DataSection from '../components/account/DataSection'
import MyShares from '../components/share/MyShares'

// One failing section must not take the page down.
function SectionFailed() {
  const { t } = useTranslation('profile')
  return (
    <p role="status" data-tid="account.sectionFailed" className="rounded-xl border border-slate-200 p-4 text-sm text-slate-500">
      {t('page.sectionFailed')}
    </p>
  )
}

class SectionBoundary extends Component {
  state = { failed: false }
  static getDerivedStateFromError() { return { failed: true } }
  componentDidCatch(error) { console.error('Account section failed to render', error) }
  render() { return this.state.failed ? <SectionFailed /> : this.props.children }
}

export default function AccountPage() {
  const { token } = useAuth()
  const { t } = useTranslation('profile')
  const location = useLocation()
  const navigate = useNavigate()
  // Set by the OAuth callback after a link attempt: {toast, toast_tone?: 'error'}.
  // Kept in component state and cleared from history, so a reload doesn't replay it.
  const [notice] = useState(() => {
    const text = location.state?.toast
    return typeof text === 'string' && text ? { text, error: location.state?.toast_tone === 'error' } : null
  })
  useEffect(() => {
    if (location.state?.toast) navigate(location.pathname, { replace: true, state: null })
  }, []) // once, on arrival
  const [account, setAccount] = useState(null) // null: loading, or the API is unavailable (404)

  // /account exists only where /config says features.accounts (else: Profile only, no probe).
  const { config, loaded } = useClientConfig()
  const accounts = loaded && featureOn(config, 'accounts')

  const load = useCallback(async () => {
    if (!token || !accounts) return
    try {
      setAccount(await getAccount(token))
    } catch (err) {
      // No account API (404) hides the editing; any other error keeps what we had.
      if (err?.status === 404) setAccount(null)
    }
  }, [token, accounts])
  useEffect(() => { load() }, [load])

  const props = { account, reload: load }
  return (
    <main className="mx-auto max-w-3xl space-y-6 px-4 py-6" data-tid="account.page">
      {notice && !notice.error && (
        <p role="status" data-tid="account.toast" className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800">{notice.text}</p>
      )}
      {notice?.error && (
        <p role="alert" data-tid="account.toast.error" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">{notice.text}</p>
      )}
      <h1 className="text-2xl font-bold text-slate-800">{t('page.title')}</h1>
      {[ProfileSection, SettingsSection, SecuritySection, QuotaSection, GameSection, MyShares, DataSection].map((Section, i) => (
        <SectionBoundary key={i}><Section {...props} /></SectionBoundary>
      ))}
    </main>
  )
}
