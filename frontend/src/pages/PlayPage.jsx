import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, Navigate } from 'react-router-dom'
import { useClientConfig, featureOn } from '../hooks/useClientConfig'
import { useAuth } from '../context/AuthContext'
import { getAccount } from '../services/accountApi'
import { getTripStats } from '../services/tripsApi'
import { useJourney } from '../hooks/useJourney'
import { useAccountSettings } from '../components/account/SettingsSync'
import useGameMe from '../components/game/useGameMe'
import GameSection from '../components/game/GameSection'
import CountriesVisited from '../components/play/CountriesVisited'
import BucketGoalEditor from '../components/play/BucketGoalEditor'
import QuizHub from '../components/play/QuizHub'
import H2HMatch from '../components/play/H2HMatch'

function Streak({ token }) {
  const { t } = useTranslation('playYou')
  const { me } = useGameMe(token, true)
  const streak = me?.streaks?.trip_checkin
  if (!me || me.hidden || !streak) return null
  return (
    <section className="rounded-2xl bg-white p-6 shadow" data-tid="play.streak" aria-labelledby="streak-title">
      <h2 id="streak-title" className="mb-1 text-lg font-semibold text-slate-800">{t('streak.title')}</h2>
      <p className="text-sm text-slate-700" data-tid="play.streak.current">{t('streak.current', { count: streak.current })}</p>
      <p className="text-xs text-slate-500" data-tid="play.streak.longest">{t('streak.longest', { count: streak.longest })}</p>
    </section>
  )
}

export default function PlayPage({ h2hId = null }) {
  const { enabled } = useJourney()
  const { token } = useAuth()
  const { t } = useTranslation('playYou')
  const { settings } = useAccountSettings()
  const { config } = useClientConfig()
  const playOn = featureOn(config, 'play') // Phase 5: quiz, head-to-head, boards (older backends: off)
  const hidden = !!settings?.hide_game
  const [account, setAccount] = useState(null)
  const [stats, setStats] = useState(null)

  const load = useCallback(async () => {
    if (!enabled || !token || hidden) return
    getAccount(token).then(setAccount, () => setAccount(null))
    getTripStats(token).then(setStats, () => setStats(null))
  }, [enabled, token, hidden])
  useEffect(() => { load() }, [load])

  if (!enabled) return null

  if (hidden) {
    return (
      <main className="mx-auto max-w-3xl space-y-6 px-4 py-6" data-tid="play.page">
        <p data-tid="play.hidden" className="rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-600">
          {t('hidden.note')}{' '}
          <Link to="/you" data-tid="play.hidden.settings" className="font-semibold text-teal-700 underline">{t('hidden.link')}</Link>
        </p>
      </main>
    )
  }

  if (h2hId && playOn) {
    return (
      <main className="mx-auto max-w-3xl space-y-6 px-4 py-6" data-tid="play.page">
        <h1 className="text-2xl font-bold text-slate-800">{t('page.title')}</h1>
        <H2HMatch token={token} id={h2hId} />
      </main>
    )
  }
  if (h2hId) return <Navigate to="/play" replace />

  return (
    <main className="mx-auto max-w-3xl space-y-6 px-4 py-6" data-tid="play.page">
      <h1 className="text-2xl font-bold text-slate-800">{t('page.title')}</h1>
      {playOn && <QuizHub token={token} />}
      <GameSection account={account} />
      <Streak token={token} />
      {stats && (
        <>
          <CountriesVisited countries={stats.countries || []} continents={stats.continents || []} goal={stats.bucket_goal} />
          <BucketGoalEditor token={token} goal={stats.bucket_goal}
            onSaved={(n) => setStats((s) => ({ ...s, bucket_goal: n }))} />
        </>
      )}
    </main>
  )
}
