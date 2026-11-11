import { Component, useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useLocation } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { getAccount } from '../services/accountApi'
import ProfileSection from '../components/account/ProfileSection'
import SettingsSection from '../components/account/SettingsSection'
import SecuritySection from '../components/account/SecuritySection'
import QuotaSection from '../components/account/QuotaSection'
import GameSection from '../components/game/GameSection'
import DataSection from '../components/account/DataSection'

// One failing section must not take the page down.
function SectionFailed() {
  const { t } = useTranslation('profile')
  return (
    <p role="status" data-tid="account.sectionFailed" className="rounded-xl border border-slate-200 p-4 text-sm text-slate-500 dark:border-slate-700 dark:text-slate-400">
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
  const toast = useLocation().state?.toast  // set by the OAuth callback after linking
  const [account, setAccount] = useState(null) // null: loading, or the API is unavailable (404)

  const load = useCallback(async () => {
    if (!token) return
    try {
      setAccount(await getAccount(token))
    } catch (err) {
      // No account API (404) hides the editing; any other error keeps what we had.
      if (err?.status === 404) setAccount(null)
    }
  }, [token])
  useEffect(() => { load() }, [load])

  const props = { account, reload: load }
  return (
    <main className="mx-auto max-w-3xl space-y-6 px-4 py-6" data-tid="account.page">
      {toast && (
        <p role="status" data-tid="account.toast" className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-200">{toast}</p>
      )}
      <h1 className="text-2xl font-bold text-slate-800 dark:text-slate-100">{t('page.title')}</h1>
      {[ProfileSection, SettingsSection, SecuritySection, QuotaSection, GameSection, DataSection].map((Section, i) => (
        <SectionBoundary key={i}><Section {...props} /></SectionBoundary>
      ))}
    </main>
  )
}
