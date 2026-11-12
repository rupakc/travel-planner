import { useCallback, useEffect, useRef, useState } from 'react'
import { Trans, useTranslation } from 'react-i18next'
import { AlertTriangle, Check, ExternalLink, Loader2, LocateFixed, MapPin, RefreshCw } from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import { fmtNumber } from '../i18n/format'
import { fetchNearby } from '../services/api'
import { listTrips, putPlace } from '../services/tripsApi'
import { useJourney } from '../hooks/useJourney'
import { announceGame } from '../game/announce'
import { enqueue } from '../offline/outbox'
import { emit } from '../telemetry/client'
import { placeKey } from '../utils/placeKey'
import { localToday } from '../utils/tripPhase'
import { track } from '../utils/analytics'
import {
  NEARBY_SECTIONS, browserLanguage, geoErrorMessage, liveErrorMessage, nearbySections, placeLabel, roundCoord,
  safeHttpUrl, usableSources,
} from '../utils/liveResults'

const GEO_OPTIONS = { enableHighAccuracy: false, timeout: 15000, maximumAge: 5 * 60 * 1000 }
// The geolocation timeout only starts once permission is granted: a dismissed
// (not blocked) prompt in Firefox/Safari never calls back. Give up after this.
export const GEO_WATCHDOG_MS = 20000

// Google-Maps-grounded items (the v2 sections) may not be stored: Google's terms
// keep them with the requesting user. Only non-Google local-data results can be
// saved to a trip with "I'm here".
export const fromMaps = (item, data) => !!(item?.maps_uri || item?.place_id || data?.attribution || data?.sources)

function ItemCard({ item, onHere, visited }) {
  const { t } = useTranslation('misc')
  const { t: tt } = useTranslation('nearbyTrip')
  const href = safeHttpUrl(item.maps_uri)
  return (
    <li className="flex flex-col rounded-xl border border-slate-100 bg-white p-4 shadow-sm">
      <h3 className="font-semibold text-slate-900">{item.name}</h3>
      {item.summary && <p className="mt-1 flex-1 text-sm text-slate-600">{item.summary}</p>}
      {href && (
        <a href={href} target="_blank" rel="noopener noreferrer"
          aria-label={t('nearby.openMapsAria', { name: item.name })}
          data-tid="nearby.open-maps"
          className="mt-3 inline-flex items-center gap-1.5 self-start rounded-full border border-slate-200 px-3 py-1 text-xs font-medium text-sky-700 hover:border-sky-300 hover:bg-sky-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-500">
          <ExternalLink size={12} aria-hidden="true" /> {t('nearby.openMaps')}
        </a>
      )}
      {onHere && (visited ? (
        <span data-tid="nearby.visited"
          className="mt-3 inline-flex items-center gap-1.5 self-start rounded-full bg-teal-50 px-3 py-1 text-xs font-semibold text-teal-800">
          <Check size={12} aria-hidden="true" /> {tt('visited')}
        </span>
      ) : (
        <button type="button" onClick={() => onHere(item)} data-tid="nearby.here"
          aria-label={tt('hereAria', { name: item.name })}
          className="mt-3 inline-flex min-h-[44px] items-center gap-1.5 self-start rounded-full bg-teal-700 px-4 py-1 text-xs font-semibold text-white hover:bg-teal-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-teal-500 sm:min-h-0">
          <MapPin size={12} aria-hidden="true" /> {tt('here')}
        </button>
      ))}
    </li>
  )
}

function SkeletonSection({ title }) {
  return (
    <section aria-hidden="true" className="space-y-3">
      <h2 className="text-sm font-semibold text-slate-700">{title}</h2>
      <ul className="grid gap-3 sm:grid-cols-2">
        {[0, 1].map(i => (
          <li key={i} className="h-28 animate-pulse rounded-xl border border-slate-100 bg-white/70 p-4">
            <div className="h-4 w-1/2 rounded bg-slate-200" />
            <div className="mt-3 h-3 w-5/6 rounded bg-slate-100" />
            <div className="mt-2 h-3 w-2/3 rounded bg-slate-100" />
          </li>
        ))}
      </ul>
    </section>
  )
}

/**
 * Near me: what's around the traveller right now, from Google Maps grounding.
 * Location is asked for only after the explainer; the answer lives in this
 * component's state and is gone when the page is left (never stored).
 */
export default function NearbyPage() {
  const { t } = useTranslation('misc')
  const { token, user } = useAuth()
  const { t: tt } = useTranslation('nearbyTrip')
  const { enabled: journey } = useJourney()
  const [tripId, setTripId] = useState(null)   // pinned trip, only while on the road
  const [visited, setVisited] = useState(() => new Set())
  const [tripNote, setTripNote] = useState('')
  const here = useRef(null)                    // last located coordinates
  // intro → locating → loading → done | error
  const [phase, setPhase] = useState('intro')
  const [error, setError] = useState(null)   // { kind: 'geo'|'api', code, text, retry }
  const [data, setData] = useState(null)
  const run = useRef(0)
  const watchdog = useRef(null)
  const headingRef = useRef(null)
  const startRef = useRef(null)

  const clearWatchdog = () => { clearTimeout(watchdog.current); watchdog.current = null }
  useEffect(() => () => { run.current += 1; clearWatchdog() }, []) // drop answers that land after leaving

  // "I'm here" only with the journey on and the pinned trip on the road
  useEffect(() => {
    if (!journey || !token) { setTripId(null); return undefined }
    let live = true
    listTrips(token).then((res) => {
      const pinned = res?.trips?.find((tr) => tr.id === res.pinned_id)
      if (live) setTripId(pinned?.phase === 'on_the_road' ? pinned.id : null)
    }).catch(() => { if (live) setTripId(null) })
    return () => { live = false }
  }, [journey, token])

  const imHere = useCallback(async (item) => {
    const key = placeKey('nearby', item.name)
    const body = { name: item.name, kind: 'nearby', visited: true, day: localToday() }
    const lat = Number.isFinite(item.lat) ? item.lat : here.current?.lat
    const lng = Number.isFinite(item.lng) ? item.lng : here.current?.lng
    if (Number.isFinite(lat) && Number.isFinite(lng)) { body.lat = lat; body.lng = lng }
    try { emit('today_action', { action: 'visited' }) } catch { /* telemetry never blocks */ }
    setTripNote('')
    try {
      const res = await putPlace(token, tripId, key, body)
      setVisited((v) => new Set(v).add(key))
      announceGame(res?.game)
    } catch (err) {
      if (err?.code !== 'network') { setTripNote(tt('failed')); return }
      await enqueue(user?.id, { method: 'PUT', path: `/trips/${tripId}/places/${encodeURIComponent(key)}`, body, key: `place:${tripId}:${key}` })
      setVisited((v) => new Set(v).add(key))
      setTripNote(tt('queued'))
    }
  }, [token, tripId, user, tt])

  const load = useCallback(async (coords, id) => {
    setPhase('loading')
    try {
      const res = await fetchNearby({
        lat: roundCoord(coords.latitude), lng: roundCoord(coords.longitude), language: browserLanguage(),
      }, token)
      if (run.current !== id) return
      here.current = { lat: roundCoord(coords.latitude), lng: roundCoord(coords.longitude) }
      setData(res)
      setPhase('done')
      track('nearby_loaded', 'nearby')
    } catch (err) {
      if (run.current !== id) return
      setError({ kind: 'api', ...liveErrorMessage(err, 'nearby') })
      setPhase('error')
    }
  }, [token])

  const locate = useCallback(() => {
    const id = ++run.current
    clearWatchdog()
    setError(null)
    setData(null)
    const geo = typeof navigator !== 'undefined' ? navigator.geolocation : null
    if (!geo?.getCurrentPosition) {
      setError({ kind: 'geo', retry: false, ...geoErrorMessage('unsupported') })
      setPhase('error')
      return
    }
    setPhase('locating')
    const fail = (code) => {
      if (run.current !== id) return
      run.current += 1 // a late answer from the browser is ignored
      clearWatchdog()
      setError({ kind: 'geo', retry: true, ...geoErrorMessage(code) })
      setPhase('error')
    }
    watchdog.current = setTimeout(() => fail(3), GEO_WATCHDOG_MS)
    geo.getCurrentPosition(
      (pos) => {
        if (run.current !== id) return
        clearWatchdog()
        load(pos.coords, id)
      },
      (err) => fail(err?.code),
      GEO_OPTIONS,
    )
  }, [load])

  // Stop waiting for the browser (e.g. its prompt was dismissed) and go back to the start
  const cancel = useCallback(() => {
    run.current += 1
    clearWatchdog()
    setPhase('intro')
    requestAnimationFrame(() => startRef.current?.focus())
  }, [])

  // Move focus to the result heading so keyboard and screen-reader users land on it
  useEffect(() => {
    if (phase === 'done' || phase === 'error') headingRef.current?.focus()
  }, [phase])

  const busy = phase === 'locating' || phase === 'loading'
  const sections = phase === 'done' ? nearbySections(data) : []
  const total = sections.reduce((n, s) => n + s.items.length, 0)
  const sources = phase === 'done' ? usableSources(data?.sources) : []
  // Section titles/empty lines and the browser-geolocation and network errors
  // come from utils/liveResults.js in English; translate them by id/code. A
  // title or message the backend supplied is shown as it came.
  const sectionTitle = (s) => {
    const def = NEARBY_SECTIONS.find(x => x.id === s.id)
    return def && s.title === def.title ? t(`nearby.section.${s.id}`) : s.title
  }
  const errorText = (e) => {
    if (!e) return ''
    if (e.kind === 'geo' && ['denied', 'unavailable', 'timeout', 'unsupported'].includes(e.code)) return t(`nearby.geo.${e.code}`)
    if (e.kind === 'api' && ['network', 'grounding_unavailable'].includes(e.code)) return t(`nearby.api.${e.code}`)
    return e.text
  }
  const status = phase === 'locating' ? t('nearby.finding')
    : phase === 'loading' ? t('nearby.looking')
      : phase === 'done' ? t('nearby.found', { count: total, place: data?.place?.name || t('nearby.you') })
        : phase === 'error' ? errorText(error) : ''

  return (
    <main className="mx-auto max-w-4xl px-4 pb-16 pt-8 sm:px-6">
      <header className="mb-6 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="font-display text-2xl font-bold text-slate-900">{t('nearby.title')}</h1>
          <p className="mt-1 max-w-xl text-sm text-slate-600">
            {t('nearby.subtitle')}
          </p>
        </div>
        {phase === 'done' && (
          <button type="button" onClick={locate} data-tid="nearby.refresh"
            className="inline-flex items-center gap-1.5 rounded-full border border-slate-300 bg-white px-3.5 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-500">
            <RefreshCw size={13} aria-hidden="true" /> {t('nearby.refresh')}
          </button>
        )}
      </header>

      <p className="sr-only" role="status" aria-live="polite" data-testid="nearby-status">{status}</p>

      {phase === 'intro' && (
        <section aria-labelledby="nearby-intro" className="rounded-2xl border border-white/60 bg-white/90 px-6 py-8 text-center">
          <span className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-sky-50 text-sky-600">
            <MapPin size={22} aria-hidden="true" />
          </span>
          <h2 id="nearby-intro" className="mt-4 text-lg font-semibold text-slate-900">{t('nearby.introTitle')}</h2>
          <p className="mx-auto mt-2 max-w-md text-sm text-slate-600">
            {t('nearby.introBody')}
          </p>
          <button type="button" ref={startRef} onClick={locate} data-tid="nearby.use-location"
            className="mt-5 inline-flex items-center gap-2 rounded-full bg-sky-600 px-5 py-2 text-sm font-semibold text-white hover:bg-sky-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-500">
            <LocateFixed size={15} aria-hidden="true" /> {t('nearby.useLocation')}
          </button>
        </section>
      )}

      {busy && (
        <div aria-busy="true" data-testid="nearby-loading" className="space-y-8">
          <p className="flex flex-wrap items-center gap-2 text-sm text-slate-500">
            <Loader2 size={15} className="animate-spin" aria-hidden="true" />
            {phase === 'locating' ? t('nearby.finding') : t('nearby.looking')}
            {phase === 'locating' && (
              <button type="button" onClick={cancel} data-tid="nearby.cancel"
                className="ml-1 rounded-full border border-slate-300 bg-white px-3 py-1 text-xs font-semibold text-slate-700 hover:bg-slate-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-500">
                {t('nearby.cancel')}
              </button>
            )}
          </p>
          {phase === 'loading' && NEARBY_SECTIONS.map(s => <SkeletonSection key={s.id} title={t(`nearby.section.${s.id}`)} />)}
        </div>
      )}

      {phase === 'error' && error && (
        <div role="alert" className="rounded-2xl border border-amber-200 bg-amber-50 px-5 py-5 text-amber-900">
          <h2 ref={headingRef} tabIndex={-1} className="flex items-center gap-2 font-semibold focus:outline-none">
            <AlertTriangle size={16} aria-hidden="true" />
            {error.kind === 'geo' ? t('nearby.geoErrorTitle') : t('nearby.apiErrorTitle')}
          </h2>
          <p className="mt-1 text-sm">{errorText(error)}</p>
          {(error.retry || error.code === 'no_place') && (
            <button type="button" onClick={locate} data-tid="nearby.retry"
              className="mt-3 rounded-full border border-amber-300 bg-white px-3 py-1 text-xs font-semibold hover:bg-amber-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-500">
              {error.code === 'no_place' ? t('nearby.checkAgain') : t('nearby.tryAgain')}
            </button>
          )}
        </div>
      )}

      {phase === 'done' && (
        <div className="space-y-8">
          <div>
            <h2 ref={headingRef} tabIndex={-1} className="font-display text-xl font-semibold text-slate-900 focus:outline-none">
              {placeLabel(data?.place) || t('nearby.aroundYou')}
            </h2>
            {data?.place?.distance_km != null && (
              <p className="mt-0.5 text-xs text-slate-500">
                {t('nearby.distance', { km: fmtNumber(Number(data.place.distance_km), { maximumFractionDigits: 1 }) })}
              </p>
            )}
          </div>

          {tripNote && <p role="status" className="text-sm text-slate-600" data-tid="nearby.trip-note">{tripNote}</p>}

          {sections.map(s => (
            <section key={s.id} aria-labelledby={`nearby-${s.id}`} data-testid={`nearby-section-${s.id}`} className="space-y-3">
              <h2 id={`nearby-${s.id}`} className="text-sm font-semibold text-slate-700">
                {sectionTitle(s)} <span className="font-normal text-slate-400">({s.items.length})</span>
              </h2>
              {s.items.length > 0 ? (
                <ul className="grid gap-3 sm:grid-cols-2">
                  {s.items.map((item, i) => <ItemCard key={item.place_id || `${item.name}-${i}`} item={item}
                    onHere={tripId && !fromMaps(item, data) ? imHere : null} visited={visited.has(placeKey('nearby', item.name))} />)}
                </ul>
              ) : (
                <p className="rounded-xl bg-white/70 px-4 py-4 text-sm text-slate-500">{t(`nearby.empty.${s.id}`)}</p>
              )}
            </section>
          ))}

          <footer className="space-y-2 border-t border-slate-200/70 pt-4 text-xs text-slate-500">
            <p data-testid="nearby-attribution">
              <Trans t={t} i18nKey="nearby.attribution" components={{
                src: <span className="font-medium text-slate-700" translate="no">{data?.attribution || 'Google Maps'}</span>,
              }} />
            </p>
            {sources.length > 0 && (
              <div>
                <h2 className="font-semibold text-slate-600">{t('nearby.sources')}</h2>
                <ul className="mt-1 space-y-0.5">
                  {sources.map(src => (
                    <li key={src.index}>
                      <a href={src.uri} data-tid="nearby.source" target="_blank" rel="noopener noreferrer" className="text-sky-700 underline-offset-2 hover:underline">
                        {src.title}
                      </a>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </footer>
        </div>
      )}
    </main>
  )
}
