import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../context/AuthContext'
import { useJourney } from '../hooks/useJourney'
import { useAccountSettings } from '../components/account/SettingsSync'
import { listTrips, getPrep, getTripStats } from '../services/tripsApi'
import { emit } from '../telemetry/client'
import TripCard from '../components/trips/TripCard'
import NextTripPanel from '../components/trips/NextTripPanel'
import CreateTripDialog from '../components/trips/CreateTripDialog'
import BucketRing from '../components/trips/BucketRing'

// The Trips hub: the pinned trip's "what now" panel, then every trip grouped
// by phase (most pressing first, the order the server sorts in).
const PHASE_ORDER = ['on_the_road', 'ready', 'planning', 'dreaming', 'memories']

export default function TripsPage() {
  const { t } = useTranslation('trips')
  const { token } = useAuth()
  const { enabled } = useJourney()
  const { settings } = useAccountSettings()
  const [data, setData] = useState(null)
  const [stats, setStats] = useState(null)
  const [prep, setPrep] = useState(null)
  const [failed, setFailed] = useState(false)
  const [creating, setCreating] = useState(false)
  const viewed = useRef(false)

  const load = useCallback(async () => {
    setFailed(false)
    try {
      const res = await listTrips(token)
      setData(res)
      if (!viewed.current) {
        viewed.current = true
        const pinned = res.trips.find((tr) => tr.id === res.pinned_id)
        emit('trip_view', { surface: 'hub', phase: pinned?.phase ?? 'none' })
      }
      getTripStats(token).then(setStats).catch(() => setStats(null))
    } catch {
      setFailed(true)
    }
  }, [token])

  useEffect(() => {
    if (enabled && token) load()
  }, [enabled, token, load])

  const pinned = data?.trips?.find((tr) => tr.id === data.pinned_id) ?? null
  const pinnedId = pinned?.id
  const pinnedReady = pinned?.phase === 'ready'

  useEffect(() => {
    setPrep(null)
    if (!pinnedReady) return undefined
    let live = true
    getPrep(token, pinnedId).then((p) => { if (live) setPrep(p) }).catch(() => {})
    return () => { live = false }
  }, [token, pinnedId, pinnedReady])

  if (!enabled) return null

  const onCreated = (trip) => {
    setCreating(false)
    setData((d) => ({ ...(d ?? { pinned_id: null }), trips: [trip, ...(d?.trips ?? [])] }))
  }

  const trips = data?.trips ?? []
  const showRing = !settings?.hide_game && stats?.bucket_goal
  const groups = PHASE_ORDER
    .map((phase) => ({ phase, items: trips.filter((tr) => tr.phase === phase && tr.id !== pinnedId) }))
    .filter((g) => g.items.length)

  return (
    <main data-tid="trips-hub" className="mx-auto max-w-3xl space-y-5 px-4 py-6">
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-2xl font-bold text-slate-900 dark:text-slate-100">{t('title')}</h1>
        <button
          type="button" data-tid="trips-create" data-tour="trips-create" onClick={() => setCreating(true)}
          className="min-h-[44px] rounded-lg bg-teal-700 px-4 py-2 text-sm font-medium text-white hover:bg-teal-800"
        >{t('create.open')}</button>
      </div>

      {failed && (
        <div role="alert" className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800 dark:border-red-800 dark:bg-red-950 dark:text-red-200">
          <p>{t('load.failed')}</p>
          <button
            type="button" data-tid="trips-retry" onClick={load}
            className="mt-2 min-h-[44px] rounded-lg bg-teal-700 px-4 py-2 font-medium text-white hover:bg-teal-800"
          >{t('load.retry')}</button>
        </div>
      )}
      {!data && !failed && <p className="text-sm text-slate-600 dark:text-slate-300">{t('load.loading')}</p>}

      {data && (
        <>
          {showRing && <BucketRing count={stats.countries?.length ?? 0} goal={stats.bucket_goal} />}
          {pinned && <NextTripPanel trip={pinned} prep={prep} />}
          {trips.length === 0 ? (
            <section data-tid="trips-empty" className="rounded-2xl border border-dashed border-slate-300 p-6 text-center dark:border-slate-600">
              <p className="text-slate-700 dark:text-slate-200">{t('empty.text')}</p>
              <div className="mt-4 flex flex-wrap justify-center gap-2">
                <Link
                  to="/explore" data-tid="trips-empty-plan"
                  className="inline-flex min-h-[44px] items-center rounded-lg bg-teal-700 px-4 py-2 text-sm font-medium text-white hover:bg-teal-800"
                >{t('empty.plan')}</Link>
                <button
                  type="button" data-tid="trips-empty-idea" onClick={() => setCreating(true)}
                  className="min-h-[44px] rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-800 dark:border-slate-600 dark:text-slate-100"
                >{t('empty.idea')}</button>
              </div>
            </section>
          ) : groups.map(({ phase, items }) => (
            <section key={phase} data-tid={`trips-group-${phase}`} aria-label={t(`phases.${phase}`)}>
              <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-600 dark:text-slate-300">
                {t(`phases.${phase}`)} <span className="font-normal">({items.length})</span>
              </h2>
              <div className="grid gap-3 sm:grid-cols-2">{items.map((tr) => <TripCard key={tr.id} trip={tr} />)}</div>
            </section>
          ))}
        </>
      )}

      {creating && <CreateTripDialog onClose={() => setCreating(false)} onCreated={onCreated} />}
    </main>
  )
}
