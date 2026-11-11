import ProfileSection from '../components/account/ProfileSection'
import SettingsSection from '../components/account/SettingsSection'
import SecuritySection from '../components/account/SecuritySection'
import QuotaSection from '../components/account/QuotaSection'
import GameSection from '../components/game/GameSection'
import DataSection from '../components/account/DataSection'

export default function AccountPage() {
  return (
    <>
      <ProfileSection />
      <SettingsSection />
      <SecuritySection />
      <QuotaSection />
      <GameSection />
      <DataSection />
    </>
  )
}
