import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Loader2, WifiOff } from 'lucide-react'
import { useJourney } from '../hooks/useJourney'
import { useAuth } from '../context/AuthContext'
import { getTrip, patchTrip, deleteTrip, notifyTripsChanged } from '../services/tripsApi'
import { errorText } from '../services/apiError'
import { emit } from '../telemetry/client'
import { useOfflinePack } from '../offline/useOfflinePack'
import { useOnline } from '../offline/useOnline'
import { resolveTabs } from '../journey/tripTabs'
import { tripPath } from '../journey/paths'
import { effectivePhase, dayIndex, daysToStart, localToday } from '../utils/tripPhase'
import TripHeader from '../components/trips/TripHeader'
import TripTabs from '../components/trips/TripTabs'
import TripOverview from '../components/trips/TripOverview'
import PrepChecklist from '../components/trips/PrepChecklist'
import TodayView from '../components/trips/TodayView'
import ExpenseLog from '../components/trips/ExpenseLog'
import Journal from '../components/trips/Journal'
import Recap from '../components/trips/Recap'
import OfflinePack from '../components/trips/OfflinePack'
import TripPricesCard from '../components/alerts2/TripPricesCard'

const PANELS = {
  overview: TripOverview,
  prep: PrepChecklist,
  today: TodayView,
  money: ExpenseLog,
  journal: Journal,
  recap: Recap,
  offline: OfflinePack,
}

// The saved plan behind a trip (same id): selections + search_data, which the
// Trip view doesn't carry. There is no shared client for it, so it is fetched
// here as PlanViewModal does.
async function fetchPlan(token, id) {
  const res = await fetch(`/api/plans/${encodeURIComponent(id)}`, { headers: { Authorization: `Bearer ${token}` } })
  if (!res.ok) throw new Error(`plan ${res.status}`)
  return res.json()
}

// The header fields of an offline pack, as a read-only Trip (phase from the
// dates on this device). The pack carries no phase override, so a manual
// stage shows as the date-based one while offline.
function tripFromPack(pack) {
  const today = localToday()
  const start = pack.start_date ?? null
  const end = pack.end_date ?? null
  const cities = (pack.destinations || []).map((d) => d?.city).filter(Boolean)
  return {
    id: pack.trip_id,
    title: pack.title,
    destination: cities[0] ?? '',
    destinations: cities,
    start_date: start,
    end_date: end,
    phase: effectivePhase({ start, end, today }),
    phase_source: 'auto',
    days_to_start: daysToStart(start, today),
    day_index: dayIndex(start, end, today),
    selections: pack.selections ?? {},
  }
}

/** Props: {tripId: number, tab: string | null} (null: the phase's default tab). */
export default function TripPage({ tripId, tab }) {
  const { enabled } = useJourney()
  if (!enabled) return null
  return <TripScreen key={tripId} tripId={tripId} tab={tab} />
}

function TripScreen({ tripId, tab }) {
  const { t } = useTranslation(['trip', 'errors'])
  const navigate = useNavigate()
  const { token, user } = useAuth()
  const online = useOnline()
  const { offlinePack } = useJourney()
  const { pack, savedAt, loading: packLoading } = useOfflinePack(user?.id ?? null, tripId)
  const [load, setLoad] = useState({ status: 'loading', trip: null, err: null })
  const [plan, setPlan] = useState({ status: 'loading', plan: null })

  const fetchTrip = useCallback(() => {
    setLoad((l) => ({ ...l, status: 'loading' }))
    return getTrip(token, tripId).then(
      (trip) => setLoad({ status: 'ok', trip, err: null }),
      (err) => setLoad({
        status: err?.code === 'network' ? 'network' : err?.status === 404 ? 'notFound' : 'error',
        trip: null,
        err,
      }),
    )
  }, [token, tripId])

  const loadPlan = useCallback(() => {
    setPlan({ status: 'loading', plan: null })
    return fetchPlan(token, tripId).then(
      (p) => setPlan({ status: 'ready', plan: p }),
      () => setPlan({ status: 'error', plan: null }),
    )
  }, [token, tripId])

  useEffect(() => {
    fetchTrip()
    loadPlan()
  }, [fetchTrip, loadPlan])

  // Back online after an offline open: ask again.
  const wasOnline = useRef(online)
  useEffect(() => {
    if (online && !wasOnline.current && load.status === 'network') { fetchTrip(); loadPlan() }
    wasOnline.current = online
  }, [online, load.status, fetchTrip, loadPlan])

  const offline = load.status === 'network'
  const base = load.status === 'ok' ? load.trip : offline && pack ? tripFromPack(pack) : null
  // Tabs get the Trip with the plan's selections and search_data (R26);
  // offline, the selections come from the pack and there is no search_data.
  const trip = base && !offline
    ? { ...base, selections: plan.plan?.selections ?? {}, search_data: plan.plan?.search_data ?? {} }
    : base
  const phase = trip?.phase ?? null
  const { tabs, enabled, active } = resolveTabs({ phase, tab, offline, offlinePack })

  // A save from the inline plan (Overview) updates the copy every tab reads,
  // so a remount or another tab never shows (or re-saves) the stale plan.
  const onPlanSaved = useCallback((updated) => {
    if (!updated || typeof updated !== 'object') return
    setPlan((p) => ({ status: 'ready', plan: { ...(p.plan || {}), ...updated } }))
  }, [])

  useEffect(() => {
    if (!phase) return
    emit('trip_view', { surface: active, phase })
  }, [active, phase])

  const onPatch = useCallback(async (changes, action) => {
    const updated = await patchTrip(token, tripId, changes)
    setLoad({ status: 'ok', trip: updated, err: null })
    emit('trip_action', { action })
    // The hub groups and sorts by phase and dates and shows the title.
    notifyTripsChanged()
    return updated
  }, [token, tripId])

  const [deleteError, setDeleteError] = useState('')
  const onDelete = useCallback(async () => {
    if (!window.confirm(t('header.confirmDelete', { title: trip?.title ?? '' }))) return
    setDeleteError('')
    try {
      await deleteTrip(token, tripId)
      emit('trip_action', { action: 'delete' })
      notifyTripsChanged()
      navigate('/trips', { replace: true })
    } catch (err) {
      setDeleteError(errorText(t, err))
    }
  }, [t, trip?.title, token, tripId, navigate])

  const shell = (children) => (
    <main className="mx-auto max-w-5xl space-y-4 px-4 py-4 sm:py-6" data-tid="trip.page">{children}</main>
  )

  if (load.status === 'loading' || (offline && packLoading)) {
    return shell(
      <div role="status" aria-label={t('loading')} data-tid="trip.loading" className="space-y-4">
        <div className="h-32 rounded-2xl bg-white/60 animate-pulse motion-reduce:animate-none" />
        <div className="h-11 w-2/3 rounded-full bg-white/60 animate-pulse motion-reduce:animate-none" />
        <div className="h-64 rounded-2xl bg-white/60 animate-pulse motion-reduce:animate-none" />
      </div>,
    )
  }

  if (!trip) {
    const notFound = load.status === 'notFound'
    return shell(
      <div data-tid={notFound ? 'trip.notFound' : offline ? 'trip.offlineEmpty' : 'trip.error'}
        className="rounded-2xl border border-white/60 bg-white/80 p-6 text-center shadow-sm">
        {offline && <WifiOff size={28} className="mx-auto mb-2 text-amber-700" aria-hidden="true" />}
        <p className="text-sm text-gray-700">
          {notFound ? errorText(t, load.err) : offline ? t('offline.empty') : t('error.failed')}
        </p>
        <div className="mt-4 flex flex-wrap justify-center gap-2">
          {!notFound && (
            <button type="button" onClick={() => { fetchTrip(); loadPlan() }} data-tid="trip.retry"
              className="min-h-[44px] rounded-lg bg-teal-700 px-5 text-sm font-semibold text-white hover:bg-teal-800">
              {offline ? t('offline.retry') : t('error.retry')}
            </button>
          )}
          <button type="button" onClick={() => navigate('/trips')} data-tid="trip.toTrips"
            className="min-h-[44px] rounded-lg border border-gray-300 bg-white px-5 text-sm font-medium text-gray-700 hover:bg-gray-50">
            {t('allTrips')}
          </button>
        </div>
      </div>,
    )
  }

  const Panel = PANELS[active] ?? TripOverview
  // Offline the selections come from the pack, so the plan counts as ready.
  const planStatus = offline ? 'ready' : plan.status
  const extra = active === 'overview' ? { plan: plan.plan, onPlanSaved } : {}
  // Overview shows its own plan skeleton / error; every other tab gets this strip.
  const planStrip = planStatus !== 'ready' && active !== 'overview'

  return shell(
    <>
      <TripHeader trip={trip} offline={offline} savedAt={savedAt} onPatch={onPatch} onDelete={onDelete} />
      {deleteError && <p role="alert" data-tid="trip.deleteError" className="text-sm text-red-700">{deleteError}</p>}
      <TripTabs tabs={tabs} enabled={enabled} active={active} onSelect={(next) => navigate(tripPath(tripId, next))} />
      <section role="tabpanel" id={`trip-panel-${active}`} aria-labelledby={`trip-tab-${active}`} data-tid={`trip.panel.${active}`}
        className="space-y-3">
        {planStrip && planStatus === 'loading' && (
          <p role="status" data-tid="trip.planLoading" className="flex items-center gap-2 rounded-lg bg-white/70 px-3 py-2 text-sm text-gray-600">
            <Loader2 size={14} className="animate-spin motion-reduce:animate-none" aria-hidden="true" /> {t('planLoading')}
          </p>
        )}
        {planStrip && planStatus === 'error' && (
          <div role="alert" data-tid="trip.planError" className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-900">
            <span>{t('overview.loadFailed')}</span>
            <button type="button" onClick={loadPlan} data-tid="trip.planRetry"
              className="min-h-[44px] rounded-lg bg-teal-700 px-4 font-semibold text-white hover:bg-teal-800">
              {t('overview.retry')}
            </button>
          </div>
        )}
        <Panel trip={trip} token={token} planStatus={planStatus} onRetryPlan={loadPlan} {...extra} />
        {active === 'overview' && !offline && <TripPricesCard planId={trip.id} token={token} />}
      </section>
    </>,
  )
}
