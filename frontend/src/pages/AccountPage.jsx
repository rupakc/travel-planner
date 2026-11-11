import { Component, useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../context/AuthContext'
import { getAccount } from '../services/accountApi'
import ProfileSection from '../components/account/ProfileSection'
import SettingsSection from '../components/account/SettingsSection'
import SecuritySection from '../components/account/SecuritySection'
import QuotaSection from '../components/account/QuotaSection'
import GameSection from '../components/game/GameSection'
import DataSection from '../components/account/DataSection'

// One failing section must not take the page down.
class SectionBoundary extends Component {
  state = { failed: false }
  static getDerivedStateFromError() { return { failed: true } }
  componentDidCatch() { /* contained */ }
  render() { return this.state.failed ? null : this.props.children }
}

export default function AccountPage() {
  const { token } = useAuth()
  const { t } = useTranslation('profile')
  const [account, setAccount] = useState(null) // null: loading, or the API is unavailable (404)

  const load = useCallback(async () => {
    if (!token) return
    try { setAccount(await getAccount(token)) } catch { setAccount(null) }
  }, [token])
  useEffect(() => { load() }, [load])

  const props = { account, reload: load }
  return (
    <main className="mx-auto max-w-3xl space-y-6 px-4 py-6" data-tid="account.page">
      <h1 className="text-2xl font-bold text-slate-800 dark:text-slate-100">{t('page.title')}</h1>
      {[ProfileSection, SettingsSection, SecuritySection, QuotaSection, GameSection, DataSection].map((Section, i) => (
        <SectionBoundary key={i}><Section {...props} /></SectionBoundary>
      ))}
    </main>
  )
}
