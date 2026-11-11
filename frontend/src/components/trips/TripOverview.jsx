import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ArrowRight, Compass } from 'lucide-react'
import { useSearchData } from '../../context/SearchDataContext'
import { getPrep } from '../../services/tripsApi'
import { emit } from '../../telemetry/client'
import PlanViewModal from '../PlanViewModal'
import CompletenessMeter from './CompletenessMeter'

// A Dreaming trip made from the hub has at most a destination: nothing was searched yet.
const hasSearch = (sd) => Boolean(sd && sd.origin && sd.destination)

// Planning only: the visa part of the meter counts when the prep visa item is
// done or not needed.
function useVisaChecked(trip, token, on) {
  const [checked, setChecked] = useState(false)
  useEffect(() => {
    if (!on || !token) return undefined
    let live = true
    getPrep(token, trip.id)
      .then((prep) => {
        const visa = (prep?.items || []).find((i) => i.id === 'visa')
        if (live) setChecked(visa?.status === 'done' || visa?.status === 'na')
      })
      .catch(() => {})
    return () => { live = false }
  }, [on, token, trip.id])
  return checked
}

/**
 * The Overview tab. Props: {trip, token} (the Trip merged with the plan's
 * selections and search_data), plus from TripPage the saved `plan`,
 * `planStatus` ('loading' | 'ok' | 'error') and `onRetryPlan`.
 * Planning: the completeness meter; then the plan (PlanViewModal inline) and
 * "Open in planner". A Dreaming trip with no search: "Plan it".
 */
export default function TripOverview({ trip, token, plan = null, planStatus = 'ok', onRetryPlan }) {
  const { t } = useTranslation('trip')
  const navigate = useNavigate()
  const { setPendingPlan, setPendingSearchData, showResults } = useSearchData()
  const planning = trip.phase === 'planning'
  const visaChecked = useVisaChecked(trip, token, planning)

  if (planStatus === 'loading') {
    return (
      <div role="status" aria-label={t('loading')} data-tid="trip.overview.loading" className="space-y-3">
        <div className="h-24 rounded-2xl bg-white/60 animate-pulse motion-reduce:animate-none" />
        <div className="h-48 rounded-2xl bg-white/60 animate-pulse motion-reduce:animate-none" />
      </div>
    )
  }
  if (planStatus === 'error' || !plan) {
    return (
      <div data-tid="trip.overview.error" className="rounded-2xl bg-white/80 p-5 text-sm text-gray-700">
        <p>{t('overview.loadFailed')}</p>
        <button type="button" onClick={onRetryPlan} data-tid="trip.overview.retry"
          className="mt-3 min-h-[44px] rounded-lg bg-teal-700 px-4 font-semibold text-white hover:bg-teal-800">
          {t('overview.retry')}
        </button>
      </div>
    )
  }

  const sd = trip.search_data ?? plan.search_data ?? {}
  const destination = trip.destination || sd.destination || ''

  if (trip.phase === 'dreaming' && !hasSearch(sd)) {
    const planIt = () => {
      emit('trip_action', { action: 'plan_it' })
      navigate('/explore', { state: { prefill: { destination } } })
    }
    return (
      <section data-tid="trip.overview.dreaming" className="rounded-2xl border border-white/60 bg-white/80 p-5 shadow-sm sm:p-6">
        <Compass size={28} className="text-teal-700" aria-hidden="true" />
        <p className="mt-2 text-sm text-gray-700">
          {destination ? t('overview.planItHint', { destination }) : t('overview.planItHintNoPlace')}
        </p>
        <button type="button" onClick={planIt} data-tid="trip.planIt"
          className="mt-4 inline-flex min-h-[44px] items-center gap-2 rounded-lg bg-teal-700 px-5 text-sm font-semibold text-white hover:bg-teal-800">
          {t('overview.planIt')} <ArrowRight size={16} aria-hidden="true" />
        </button>
      </section>
    )
  }

  const openPlanner = () => {
    emit('trip_action', { action: 'open_planner' })
    setPendingPlan(plan)
    setPendingSearchData(plan.search_data)
    showResults()
    navigate('/explore')
  }

  return (
    <div className="space-y-4" data-tid="trip.overview">
      {planning && (
        <CompletenessMeter selections={trip.selections ?? plan.selections ?? {}} searchData={sd} visaChecked={visaChecked} surface="trip" />
      )}
      <PlanViewModal plan={plan} token={token} inline />
      <div className="flex flex-col items-start gap-2 rounded-2xl border border-white/60 bg-white/80 p-4 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-sm text-gray-600">{t('overview.openPlannerHint')}</p>
        <button type="button" onClick={openPlanner} data-tid="trip.openPlanner"
          className="inline-flex min-h-[44px] shrink-0 items-center gap-2 rounded-lg bg-teal-700 px-5 text-sm font-semibold text-white hover:bg-teal-800">
          {t('overview.openPlanner')} <ArrowRight size={16} aria-hidden="true" />
        </button>
      </div>
    </div>
  )
}

