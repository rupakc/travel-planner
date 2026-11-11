import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router-dom'
import { useJourney } from '../hooks/useJourney'
import AccountPage from './AccountPage'

const LINK = 'flex min-h-[44px] items-center rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm font-semibold text-slate-800 hover:bg-slate-50'

export default function YouPage() {
  const { enabled } = useJourney()
  const { t } = useTranslation('playYou')
  const navigate = useNavigate()
  if (!enabled) return null

  const replay = () => {
    try { window.dispatchEvent(new Event('voyager:replay-journey-tour')) } catch { /* no window */ }
    navigate('/trips')
  }

  return (
    <div data-tid="you.page">
      <AccountPage />
      <nav aria-label={t('you.more')} className="mx-auto max-w-3xl space-y-3 px-4 pb-8" data-tid="you.links">
        <h2 className="text-lg font-semibold text-slate-800">{t('you.more')}</h2>
        <Link to="/preferences" data-tid="you.preferences" className={LINK}>{t('you.preferences')}</Link>
        <Link to="/alerts" data-tid="you.alerts" className={LINK}>{t('you.alerts')}</Link>
        <button type="button" onClick={replay} data-tid="you.tour" className={`${LINK} w-full text-left`}>{t('you.tour')}</button>
      </nav>
    </div>
  )
}
