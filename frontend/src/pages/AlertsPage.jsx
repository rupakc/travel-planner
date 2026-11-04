import { useCallback, useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { BellRing, Loader2, Search } from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import { useAlerts } from '../context/AlertsContext'
import { useSearchData } from '../context/SearchDataContext'
import {
  checkFareWatchNow, deleteFareWatch, listFareWatches, updateFareWatch,
} from '../services/api'
import { axiosErrorDetail } from '../utils/httpError'
import { formatUsd } from '../utils/fareCalendar'
import { replanSearchData } from '../utils/fareWatch'
import { track } from '../utils/analytics'
import WatchCard from '../components/alerts/WatchCard'

/** What one "Check now" found, in plain words (statuses: see the API). */
export function checkMessage(res) {
  switch (res.check_status) {
    case 'checked':
      if (res.notification) return { tone: 'good', text: res.notification.title }
      if (res.last_price != null) {
        return { tone: 'neutral', text: `Checked just now: ${formatUsd(res.last_price)}. Nothing worth an alert yet.` }
      }
      return { tone: 'neutral', text: 'Checked just now, but no fares were found for these dates.' }
    case 'failed':
      return { tone: 'warn', text: 'Live fares didn’t respond. We’ll try again within the hour.' }
    case 'errored':
      return { tone: 'warn', text: 'Live fares failed three times in a row, so checks are on hold. Use Retry when you’re ready.' }
    case 'expired':
      return { tone: 'neutral', text: 'This trip has departed, so we’ve stopped watching its fare.' }
    case 'postponed':
      return { tone: 'warn', text: 'Live fares are busy right now — we’ll check again tomorrow.' }
    case 'deleted':
      return { tone: 'neutral', text: 'This watch was removed.' }
    default:
      return { tone: 'neutral', text: 'Nothing was checked: this fare isn’t being watched right now.' }
  }
}

/** Every fare the traveller watches, grouped Active / Past. */
export default function AlertsPage() {
  const { token, user, preferences } = useAuth()
  const { caps, watchesChanged, refresh: refreshBell, markSeen } = useAlerts()
  const { setPendingSearchData } = useSearchData()
  const navigate = useNavigate()
  const location = useLocation()
  const params = new URLSearchParams(location.search)
  const focusId = Number(params.get('watch')) || null
  const [watches, setWatches] = useState(null)
  const [loadError, setLoadError] = useState(null)
  const [busy, setBusy] = useState({})        // watch id → action in flight
  const [messages, setMessages] = useState({}) // watch id → { tone, text }
  const handledLink = useRef(null)

  const load = useCallback(() => {
    setLoadError(null)
    listFareWatches(token)
      .then(setWatches)
      .catch(err => setLoadError(axiosErrorDetail(err).detail || 'Couldn’t load your watched fares.'))
  }, [token])

  useEffect(() => { load() }, [load])

  const replace = (w) => setWatches(list => list.map(x => (x.id === w.id ? w : x)))
  const say = (id, msg) => setMessages(m => ({ ...m, [id]: msg }))
  const withBusy = async (id, action, fn) => {
    setBusy(b => ({ ...b, [id]: action }))
    try { return await fn() } finally { setBusy(b => ({ ...b, [id]: null })) }
  }

  const replan = useCallback((w, cheapest) => {
    track('watch_replanned', 'alerts', { cheapest })
    setPendingSearchData(replanSearchData(w, preferences, { cheapest }))
    navigate('/')
  }, [preferences, setPendingSearchData, navigate])

  // Deep links (?watch=ID, &replan=1[&cheapest=1]) from the bell, toasts and emails
  useEffect(() => {
    if (!watches || !focusId || handledLink.current === location.search) return
    handledLink.current = location.search
    const w = watches.find(x => x.id === focusId)
    if (!w) return
    if (params.get('replan') === '1' && w.status !== 'expired') {
      replan(w, params.get('cheapest') === '1')
      return
    }
    requestAnimationFrame(() => {
      const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
      document.getElementById(`watch-${focusId}`)?.scrollIntoView({ block: 'start', behavior: reduce ? 'auto' : 'smooth' })
    })
  }, [watches, focusId, location.search]) // runs once per deep link

  const onCheck = (w) => withBusy(w.id, 'check', async () => {
    track('watch_checked_now', 'alerts')
    try {
      const res = await checkFareWatchNow(w.id, token)
      replace(res)
      say(w.id, checkMessage(res))
      if (res.notification) {
        markSeen(res.notification.id) // shown inline already: no toast for it
        watchesChanged()
        refreshBell()
      }
    } catch (err) {
      say(w.id, { tone: 'warn', text: axiosErrorDetail(err).detail || 'Couldn’t check right now. Try again in a moment.' })
    }
  })

  const onUpdate = (w, changes) => withBusy(w.id, changes.status ? 'status' : 'save', async () => {
    try {
      replace(await updateFareWatch(w.id, changes, token))
      watchesChanged()
      say(w.id, changes.status === 'paused' ? { tone: 'neutral', text: 'Paused. We won’t check this fare until you resume.' }
        : changes.status === 'active' ? { tone: 'neutral', text: 'Watching again.' }
          : { tone: 'neutral', text: 'Saved.' })
      return true
    } catch (err) {
      say(w.id, { tone: 'warn', text: axiosErrorDetail(err).detail || 'Couldn’t save that change.' })
      return false
    }
  })

  const onDelete = (w) => withBusy(w.id, 'delete', async () => {
    try {
      await deleteFareWatch(w.id, token)
      setWatches(list => list.filter(x => x.id !== w.id))
      watchesChanged()
    } catch (err) {
      say(w.id, { tone: 'warn', text: axiosErrorDetail(err).detail || 'Couldn’t delete this watch.' })
    }
  })

  const active = (watches || []).filter(w => w.status !== 'expired')
  const past = (watches || []).filter(w => w.status === 'expired')
  const card = (w) => (
    <WatchCard key={w.id} watch={w} highlighted={w.id === focusId} busy={busy[w.id]} message={messages[w.id]}
      emailAvailable={caps.email} hasEmail={!!user?.email}
      onCheck={() => onCheck(w)} onUpdate={(c) => onUpdate(w, c)} onDelete={() => onDelete(w)}
      onReplan={(cheapest) => replan(w, cheapest)} onBook={() => track('watch_booked', 'alerts')} />
  )

  return (
    <main className="mx-auto max-w-3xl px-4 pb-16 pt-8 sm:px-6">
      <header className="mb-6">
        <h1 className="font-display text-2xl font-bold text-slate-900">Watched fares</h1>
        <p className="mt-1 max-w-xl text-sm text-slate-600">
          We re-check these fares about twice a day and tell you only when a drop is worth knowing about.
        </p>
      </header>

      {!watches && !loadError && (
        <p className="flex items-center gap-2 text-sm text-slate-500"><Loader2 size={15} className="animate-spin" /> Loading your watched fares…</p>
      )}
      {loadError && (
        <div role="alert" className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          <span>{loadError}</span>
          <button type="button" onClick={load} className="rounded-full border border-amber-300 bg-white px-3 py-1 text-xs font-semibold hover:bg-amber-100">Try again</button>
        </div>
      )}

      {watches && watches.length === 0 && (
        <section className="rounded-2xl border border-white/60 bg-white/90 px-6 py-10 text-center">
          <span className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-sky-50 text-sky-600">
            <BellRing size={22} aria-hidden="true" />
          </span>
          <h2 className="mt-4 text-lg font-semibold text-slate-900">No fares watched yet</h2>
          <p className="mx-auto mt-2 max-w-md text-sm text-slate-600">
            {caps.fareWatch
              ? 'Search a trip, then choose “Watch fare” in the Flights section. We’ll keep an eye on the price and let you know when it drops or hits the price you want.'
              : 'Watching fares needs live flight prices, which aren’t set up on this server yet.'}
          </p>
          <button type="button" onClick={() => navigate('/')}
            className="mt-5 inline-flex items-center gap-2 rounded-full bg-sky-600 px-5 py-2 text-sm font-semibold text-white hover:bg-sky-700">
            <Search size={15} /> Search flights
          </button>
        </section>
      )}

      {active.length > 0 && (
        <section aria-labelledby="alerts-active" className="space-y-4">
          <h2 id="alerts-active" className="text-sm font-semibold text-slate-700">Active <span className="font-normal text-slate-400">({active.length})</span></h2>
          {active.map(card)}
        </section>
      )}
      {past.length > 0 && (
        <section aria-labelledby="alerts-past" className="mt-10 space-y-4">
          <h2 id="alerts-past" className="text-sm font-semibold text-slate-700">Past trips <span className="font-normal text-slate-400">({past.length})</span></h2>
          {past.map(card)}
        </section>
      )}
    </main>
  )
}
