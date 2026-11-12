import { useCallback, useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { BellRing, Loader2, Search } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import i18n from '../i18n'
import { useAuth } from '../context/AuthContext'
import { useAlerts } from '../context/AlertsContext'
import { useSearchData } from '../context/SearchDataContext'
import {
  checkFareWatchNow, checkPriceWatchNow, deleteFareWatch, deletePriceWatch, listFareWatches,
  listPriceWatches, liveCheckWatch, updateFareWatch, updatePriceWatch,
} from '../services/api'
import { axiosErrorDetail } from '../utils/httpError'
import { formatUsd } from '../utils/fareCalendar'
import { replanSearchData } from '../utils/fareWatch'
import { track } from '../utils/analytics'
import {
  ALERT_TABS, countByTab, inTab, priceCheckMessage, watchDomId,
} from '../utils/priceWatch'
import WatchCard from '../components/alerts/WatchCard'
import AlertsV2Header from '../components/alerts2/AlertsV2Header'
import { useAlertsV2 } from '../hooks/useAlertsV2'
import { cardFor } from '../components/alerts/cards'

/** What one "Check now" found, in plain words (statuses: see the API). */
export function checkMessage(res) {
  const t = (key, opts) => i18n.t(`alerts:${key}`, opts)
  switch (res.check_status) {
    case 'checked':
      if (res.notification) return { tone: 'good', text: res.notification.title }
      if (res.last_price != null) {
        return { tone: 'neutral', text: t('checks.justNow', { price: formatUsd(res.last_price) }) }
      }
      return { tone: 'neutral', text: t('checks.noFares') }
    case 'failed':
      return { tone: 'warn', text: t('checks.failed') }
    case 'errored':
      return { tone: 'warn', text: t('checks.errored') }
    case 'expired':
      return { tone: 'neutral', text: t('checks.expired') }
    case 'postponed':
      return { tone: 'warn', text: t('checks.postponed') }
    case 'deleted':
      return { tone: 'neutral', text: t('checks.deleted') }
    default:
      return { tone: 'neutral', text: t('checks.default') }
  }
}

/** Fare watches use their own API; price watches (hotel / activity / trip) theirs. */
// (Called through, not stored: each API function is looked up when used.)
const ACTIONS = {
  fare: {
    check: (...a) => checkFareWatchNow(...a), update: (...a) => updateFareWatch(...a),
    remove: (...a) => deleteFareWatch(...a), message: checkMessage, paused: 'checks.pausedFare',
  },
  price: {
    check: (...a) => checkPriceWatchNow(...a), update: (...a) => updatePriceWatch(...a),
    remove: (...a) => deletePriceWatch(...a), message: priceCheckMessage, paused: 'checks.pausedPrice',
  },
}
const actionsFor = (w) => (w.kind ? ACTIONS.price : ACTIONS.fare)
// "Search the web now": a fare watch is kind 'flight' to the live-check API.
// The answer is shown once on the card and never feeds the watch's price/history.
const liveCheckFor = (w, token) => () => {
  track('watch_live_checked', 'alerts', { kind: w.kind || 'flight' })
  return liveCheckWatch(w.kind || 'flight', w.id, token)
}
const sortDate = (w) => (w.kind ? w.expires_on : w.departure_date) || ''

/** Every fare and price the traveller watches: filter chips by kind, then Active / Past. */
export default function AlertsPage() {
  const { t } = useTranslation('alerts')
  const { on: v2 } = useAlertsV2()
  const { token, user, preferences } = useAuth()
  const { caps, watchesChanged, refresh: refreshBell, markSeen } = useAlerts()
  const { setPendingSearchData } = useSearchData()
  const navigate = useNavigate()
  const location = useLocation()
  const params = new URLSearchParams(location.search)
  const focusId = Number(params.get('watch')) || null
  const focusKind = params.get('kind') || null   // set for price watches; fares have none
  const [fares, setFares] = useState(null)
  const [prices, setPrices] = useState(null)
  const [loadError, setLoadError] = useState(null)
  const [priceError, setPriceError] = useState(false)
  const [tab, setTab] = useState('all')
  const [busy, setBusy] = useState({})        // DOM id → action in flight
  const [messages, setMessages] = useState({}) // DOM id → { tone, text }
  const handledLink = useRef(null)

  const loadPrices = useCallback(async () => {
    setPriceError(false)
    try {
      setPrices(await listPriceWatches(token))
    } catch {
      // Fare watches still show; a quiet note offers to try again
      setPrices([])
      setPriceError(true)
    }
  }, [token])

  const load = useCallback(() => {
    setLoadError(null)
    listFareWatches(token)
      .then(setFares)
      .catch(err => {
        // Price watches still show; the banner offers to try again
        setFares(list => list || [])
        setLoadError(axiosErrorDetail(err).detail || i18n.t('alerts:page.loadFailed'))
      })
    loadPrices()
  }, [token, loadPrices])

  useEffect(() => { load() }, [load])

  // Each list shows as soon as it arrives (a slow price list never holds
  // up the fare cards); "nothing watched" waits for both
  const loaded = fares !== null && prices !== null
  const watches = fares || prices
    ? [...(fares || []), ...(prices || [])].sort((a, b) => sortDate(a).localeCompare(sortDate(b)))
    : null
  const isFocus = (w) => w.id === focusId && (w.kind || null) === focusKind

  const replace = (w) => {
    const set = w.kind ? setPrices : setFares
    set(list => list.map(x => (x.id === w.id ? w : x)))
  }
  const say = (w, msg) => setMessages(m => ({ ...m, [watchDomId(w)]: msg }))
  const withBusy = async (w, action, fn) => {
    const id = watchDomId(w)
    setBusy(b => ({ ...b, [id]: action }))
    try { return await fn() } finally { setBusy(b => ({ ...b, [id]: null })) }
  }

  const replan = useCallback((w, cheapest) => {
    track('watch_replanned', 'alerts', { cheapest })
    setPendingSearchData(replanSearchData(w, preferences, { cheapest }))
    navigate('/')
  }, [preferences, setPendingSearchData, navigate])

  // Deep links from the bell, toasts and emails: ?watch=ID[&replan=1[&cheapest=1]]
  // for fares, ?kind=KIND&watch=ID for price watches
  useEffect(() => {
    if (!focusId || handledLink.current === location.search) return
    if ((focusKind ? prices : fares) === null) return // its list is still loading
    const w = watches.find(isFocus)
    if (!w) {
      // Its list failed to load: try again once it has (the "Try again" button)
      const listFailed = focusKind ? priceError : !!loadError
      if (!listFailed) handledLink.current = location.search
      return
    }
    handledLink.current = location.search
    setTab(t => (inTab(w, t) ? t : 'all')) // a filtered-out watch: show all
    if (!w.kind && params.get('replan') === '1' && w.status !== 'expired') {
      replan(w, params.get('cheapest') === '1')
      return
    }
    requestAnimationFrame(() => {
      const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
      document.getElementById(watchDomId(w))?.scrollIntoView({ block: 'start', behavior: reduce ? 'auto' : 'smooth' })
    })
  }, [fares, prices, focusId, location.search, priceError, loadError]) // once per deep link

  const onCheck = (w) => withBusy(w, 'check', async () => {
    const act = actionsFor(w)
    track('watch_checked_now', 'alerts', w.kind ? { kind: w.kind } : undefined)
    try {
      const res = await act.check(w.id, token)
      replace(res)
      say(w, act.message(res))
      if (res.notification) {
        markSeen(res.notification.id) // shown inline already: no toast for it
        watchesChanged()
        refreshBell()
      }
    } catch (err) {
      say(w, { tone: 'warn', text: axiosErrorDetail(err).detail || i18n.t('alerts:checks.checkFailed') })
    }
  })

  const onUpdate = (w, changes) => withBusy(w, changes.status ? 'status' : 'save', async () => {
    const act = actionsFor(w)
    try {
      replace(await act.update(w.id, changes, token))
      watchesChanged()
      say(w, changes.status === 'paused' ? { tone: 'neutral', text: i18n.t(`alerts:${act.paused}`) }
        : changes.status === 'active' ? { tone: 'neutral', text: i18n.t('alerts:checks.resumed') }
          : { tone: 'neutral', text: i18n.t('alerts:checks.saved') })
      return true
    } catch (err) {
      say(w, { tone: 'warn', text: axiosErrorDetail(err).detail || i18n.t('alerts:checks.saveFailed') })
      return false
    }
  })

  const onDelete = (w) => withBusy(w, 'delete', async () => {
    try {
      await actionsFor(w).remove(w.id, token)
      const set = w.kind ? setPrices : setFares
      set(list => list.filter(x => x.id !== w.id))
      watchesChanged()
    } catch (err) {
      say(w, { tone: 'warn', text: axiosErrorDetail(err).detail || i18n.t('alerts:checks.deleteFailed') })
    }
  })

  const counts = countByTab(watches)
  const shown = (watches || []).filter(w => inTab(w, tab))
  const active = shown.filter(w => w.status !== 'expired')
  const past = shown.filter(w => w.status === 'expired')
  const card = (w) => {
    const id = watchDomId(w)
    const common = {
      watch: w, highlighted: isFocus(w), busy: busy[id], message: messages[id],
      emailAvailable: caps.email, hasEmail: !!user?.email,
      onCheck: () => onCheck(w), onUpdate: (c) => onUpdate(w, c), onDelete: () => onDelete(w),
      onLiveCheck: liveCheckFor(w, token),
    }
    if (!w.kind) {
      return (
        <WatchCard key={id} {...common}
          onReplan={(cheapest) => replan(w, cheapest)} onBook={() => track('watch_booked', 'alerts')} />
      )
    }
    const Card = cardFor(w.kind)
    return <Card key={id} {...common} onOpen={() => track('watch_booked', 'alerts', { kind: w.kind })} />
  }

  return (
    <main className="mx-auto max-w-3xl px-4 pb-16 pt-8 sm:px-6">
      <header className="mb-6">
        <h1 className="font-display text-2xl font-bold text-slate-900">{t('page.title')}</h1>
        <p className="mt-1 max-w-xl text-sm text-slate-600">
          {t('page.intro')}
        </p>
      </header>
      {v2 && <AlertsV2Header />}

      {!watches && !loadError && (
        <p className="flex items-center gap-2 text-sm text-slate-500"><Loader2 size={15} className="animate-spin" /> {t('page.loading')}</p>
      )}
      {loadError && (
        <div role="alert" className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          <span>{loadError}</span>
          <button type="button" data-tid="alerts.reload" onClick={load} className="rounded-full border border-amber-300 bg-white px-3 py-1 text-xs font-semibold hover:bg-amber-100">{t('ui.tryAgain')}</button>
        </div>
      )}
      {priceError && !loadError && (
        <div data-testid="price-load-error" role="status"
          className="mb-4 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-slate-200 bg-white/80 px-4 py-2.5 text-sm text-slate-600">
          <span>{t('page.priceLoadFailed')}</span>
          <button type="button" data-tid="alerts.reload-prices" onClick={loadPrices} className="rounded-full border border-slate-300 bg-white px-3 py-1 text-xs font-semibold hover:bg-slate-50">{t('ui.tryAgain')}</button>
        </div>
      )}

      {loaded && watches.length === 0 && !loadError && (
        <section className="rounded-2xl border border-white/60 bg-white/90 px-6 py-10 text-center">
          <span className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-sky-50 text-sky-600">
            <BellRing size={22} aria-hidden="true" />
          </span>
          <h2 className="mt-4 text-lg font-semibold text-slate-900">{t('page.emptyTitle')}</h2>
          <p className="mx-auto mt-2 max-w-md text-sm text-slate-600">
            {caps.fareWatch ? t('page.emptyOn') : t('page.emptyOff')}
          </p>
          <button type="button" data-tid="alerts.search-flights" onClick={() => navigate('/')}
            className="mt-5 inline-flex items-center gap-2 rounded-full bg-sky-600 px-5 py-2 text-sm font-semibold text-white hover:bg-sky-700">
            <Search size={15} /> {t('page.searchFlights')}
          </button>
        </section>
      )}

      {watches && watches.length > 0 && (
        <div role="group" aria-label={t('page.filterLabel')} className="-mx-1 mb-5 flex gap-1.5 overflow-x-auto px-1 pb-1">
          {ALERT_TABS.map(tb => (
            <button key={tb.id} type="button" data-tid={`alerts.filter-${tb.id}`} aria-pressed={tab === tb.id} onClick={() => setTab(tb.id)}
              aria-label={t('page.tabAria', { label: t(`tabs.${tb.id}`), n: counts[tb.id] })}
              className={`inline-flex shrink-0 items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-500 ${tab === tb.id ? 'border-sky-600 bg-sky-600 text-white' : counts[tb.id] ? 'border-slate-200 bg-white text-slate-700 hover:border-slate-300' : 'border-slate-100 bg-white/60 text-slate-400'}`}>
              {t(`tabs.${tb.id}`)}<span className={`tabular-nums ${tab === tb.id ? 'text-sky-100' : 'text-slate-400'}`}>{counts[tb.id]}</span>
            </button>
          ))}
        </div>
      )}
      {watches && watches.length > 0 && (
        <p className="sr-only" aria-live="polite" data-testid="filter-status">{t(`tabs.status.${tab}`, { count: shown.length })}</p>
      )}
      {watches && watches.length > 0 && shown.length === 0 && (
        <p className="rounded-xl bg-white/70 px-4 py-6 text-center text-sm text-slate-500">
          {tab === 'all' ? t('page.nothingHere') : t(`tabs.empty.${tab}`)}
        </p>
      )}

      {active.length > 0 && (
        <section aria-labelledby="alerts-active" className="space-y-4">
          <h2 id="alerts-active" className="text-sm font-semibold text-slate-700">{t('page.active')} <span className="font-normal text-slate-400">({active.length})</span></h2>
          {active.map(card)}
        </section>
      )}
      {past.length > 0 && (
        <section aria-labelledby="alerts-past" className="mt-10 space-y-4">
          <h2 id="alerts-past" className="text-sm font-semibold text-slate-700">{t('page.past')} <span className="font-normal text-slate-400">({past.length})</span></h2>
          {past.map(card)}
        </section>
      )}
    </main>
  )
}
