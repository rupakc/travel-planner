import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { sharePlan } from '../../services/api'
import ShareDialog from '../share/ShareDialog'
import PublishIdeaButton from '../social/PublishIdeaButton'
import { sharingEnabled } from '../../utils/share'
import { useClientConfig } from '../../hooks/useClientConfig'
import { useJourney } from '../../hooks/useJourney'
import { getRecap, completeRecap } from '../../services/tripsApi'
import { announceGame } from '../../game/announce'
import { emit } from '../../telemetry/client'
import { computePlanCost } from '../../utils/planHelpers'
import { arrangeItinerary } from '../../utils/itineraryLayout'
import { scheduleDays } from '../../utils/schedule'
import { plannedRoute } from '../../utils/recapRoute'
import { fmtDate } from '../../i18n/format'
import { Stats, Spend } from './RecapStats'
import CountryReveal from './CountryReveal'
import WhereNext from './WhereNext'

const RecapMap = lazy(() => import('./RecapMap'))

const note = (action) => { try { emit('recap_action', { action }) } catch { /* telemetry never breaks the UI */ } }

export default function Recap({ trip, token }) {
  const { t } = useTranslation('recap')
  const { enabled } = useJourney()
  const [state, setState] = useState({ status: 'loading', recap: null })
  const [reveal, setReveal] = useState(null)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const { config: clientConfig } = useClientConfig()
  const sharingV2 = sharingEnabled(clientConfig)
  const [shareOpen, setShareOpen] = useState(false)
  const shareUrl = useRef(null)
  const tripId = trip?.id

  const alive = useRef(0)

  const load = useCallback((first = false) => {
    const run = ++alive.current
    setState({ status: 'loading', recap: null })
    getRecap(token, tripId)
      .then((recap) => {
        if (run !== alive.current) return
        setState({ status: 'ok', recap })
        if (first) note('view')
      })
      .catch(() => { if (run === alive.current) setState({ status: 'error', recap: null }) })
  }, [token, tripId])

  useEffect(() => {
    shareUrl.current = null
    setReveal(null); setMsg('')
    if (!enabled || !tripId) return undefined
    load(true)
    return () => { alive.current += 1 }
  }, [enabled, tripId, token, load])

  // The itinerary, plan cost and interests come from the trip (TripPage passes
  // `selections` / `search_data`); without them those parts simply stay out.
  const sel = trip?.selections
  const planned = useMemo(() => {
    if (!sel?.itinerary?.days?.length) return { points: [], km: null }
    return plannedRoute(scheduleDays(arrangeItinerary(sel.itinerary, sel.itinerary_layout, sel.itinerary_edits).days, sel.itinerary_edits))
  }, [sel])

  if (!enabled) return null
  if (state.status === 'loading') {
    return <p className="p-4 text-sm text-gray-600" role="status" data-tid="recap.loading">{t('loading')}</p>
  }
  if (state.status === 'error') {
    return (
      <div className="p-4" data-tid="recap.error">
        <p className="text-sm text-red-700" role="alert">{t('failed')}</p>
        <button type="button" onClick={() => load()} data-tid="recap.retry"
          className="mt-2 min-h-[44px] rounded-lg bg-teal-700 px-4 text-sm font-medium text-white hover:bg-teal-800">{t('retry')}</button>
      </div>
    )
  }

  const recap = state.recap
  if (!recap.can_complete && !recap.completed_at) {
    return (
      <p className="rounded-xl border border-gray-200 bg-white p-4 text-sm text-gray-800"
        data-tid="recap.not-ready">
        {t('notReady', { date: recap.end_date ? fmtDate(recap.end_date, { dateStyle: 'medium' }) : '—' })}
      </p>
    )
  }

  const usePlanned = !recap.route?.length && planned.points.length > 0
  const points = recap.route?.length ? recap.route : planned.points
  const planCost = sel ? computePlanCost(sel, trip.search_data) : 0
  const city = trip?.destination || recap.title

  const finish = async () => {
    setBusy(true); setMsg('')
    try {
      const res = await completeRecap(token, tripId)
      note('complete')
      announceGame(res?.game)
      setState((s) => ({ ...s, recap: { ...s.recap, completed_at: res.completed_at, can_complete: false } }))
      const fresh = (res?.new_countries || []).map((code) => ({
        code, name: recap.countries?.find((c) => c.code === code)?.name || code,
      }))
      if (fresh.length) setReveal(fresh)
    } catch {
      setMsg(t('finishFailed'))
    } finally { setBusy(false) }
  }

  const share = async () => {
    setBusy(true); setMsg('')
    note('share')
    try {
      if (!shareUrl.current) {
        const { share_token } = await sharePlan(token, tripId)
        shareUrl.current = `${window.location.origin}/share/${share_token}`
      }
      const text = `${t('share.days', { count: recap.days, city })} · ${t('share.places', { count: recap.visited_count })}`
      if (typeof navigator.share === 'function') {
        try {
          await navigator.share({ title: recap.title, text, url: shareUrl.current })
        } catch (err) {
          if (err?.name !== 'AbortError') throw err
        }
      } else {
        await navigator.clipboard.writeText(shareUrl.current)
        setMsg(t('share.copied'))
      }
    } catch { setMsg(t('share.failed')) }
    finally { setBusy(false) }
  }

  return (
    <div className="space-y-4" data-tid="recap.root">
      <h2 className="text-lg font-bold text-gray-900">{recap.title}</h2>
      <Stats recap={recap} plannedKm={usePlanned ? planned.km : null} />
      {points.length > 0 && (
        <div>
          <p className="mb-1 text-sm font-medium text-gray-800" data-tid="recap.map-label">
            {usePlanned ? t('map.planned') : t('map.route')}
          </p>
          <Suspense fallback={<div className="h-56 rounded-xl bg-gray-100" />}>
            <RecapMap points={points} label={usePlanned ? t('map.planned') : t('map.route')} />
          </Suspense>
        </div>
      )}
      <Spend spend={recap.spend ? { ...recap.spend } : null} planCost={planCost} />
      {reveal && <CountryReveal countries={reveal} onClose={() => setReveal(null)} />}
      <div className="flex flex-wrap items-center gap-2">
        {recap.can_complete && !recap.completed_at && (
          <button type="button" onClick={finish} disabled={busy} data-tid="recap.finish"
            className="min-h-[44px] rounded-lg bg-teal-700 px-4 text-sm font-medium text-white hover:bg-teal-800 disabled:opacity-60">
            {t('finish')}
          </button>
        )}
        {recap.completed_at && <span className="text-sm text-teal-800" data-tid="recap.completed">{t('completed')}</span>}
        {sharingV2 ? (
          <button type="button" onClick={() => setShareOpen(true)} data-tid="recap.share-link"
            className="min-h-[44px] rounded-lg border border-gray-300 px-4 text-sm font-medium text-gray-800 hover:bg-gray-50">
            {t('share.cta')}
          </button>
        ) : (
        <button type="button" onClick={share} disabled={busy} data-tid="recap.share"
          className="min-h-[44px] rounded-lg border border-gray-300 px-4 text-sm font-medium text-gray-800 hover:bg-gray-50 disabled:opacity-60">
          {t('share.cta')}
        </button>
        )}
      </div>
      {sharingV2 && shareOpen && <ShareDialog kind="recap" planId={tripId} onClose={() => setShareOpen(false)} />}
      {recap.completed_at && <PublishIdeaButton kind="recap" planId={tripId} tid="recap.publish-idea" />}
      {msg && <p className="text-sm text-gray-700" role="status" data-tid="recap.msg">{msg}</p>}
      <WhereNext key={tripId} trip={trip} onUse={() => note('where_next')} />
    </div>
  )
}
