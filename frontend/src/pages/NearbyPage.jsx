import { useCallback, useEffect, useRef, useState } from 'react'
import { AlertTriangle, ExternalLink, Loader2, LocateFixed, MapPin, RefreshCw } from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import { fetchNearby } from '../services/api'
import { track } from '../utils/analytics'
import {
  NEARBY_SECTIONS, geoErrorMessage, liveErrorMessage, nearbySections, roundCoord, safeHttpUrl, usableSources,
} from '../utils/liveResults'

const GEO_OPTIONS = { enableHighAccuracy: false, timeout: 15000, maximumAge: 5 * 60 * 1000 }

function placeLabel(place) {
  if (!place) return ''
  return [place.name, place.region, place.country].filter(Boolean).join(', ')
}

function ItemCard({ item }) {
  const href = safeHttpUrl(item.maps_uri)
  return (
    <li className="flex flex-col rounded-xl border border-slate-100 bg-white p-4 shadow-sm">
      <h3 className="font-semibold text-slate-900">{item.name}</h3>
      {item.summary && <p className="mt-1 flex-1 text-sm text-slate-600">{item.summary}</p>}
      {href && (
        <a href={href} target="_blank" rel="noopener noreferrer"
          aria-label={`Open ${item.name} in Google Maps (opens in a new tab)`}
          className="mt-3 inline-flex items-center gap-1.5 self-start rounded-full border border-slate-200 px-3 py-1 text-xs font-medium text-sky-700 hover:border-sky-300 hover:bg-sky-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-500">
          <ExternalLink size={12} aria-hidden="true" /> Open in Google Maps
        </a>
      )}
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
  const { token } = useAuth()
  // intro → locating → loading → done | error
  const [phase, setPhase] = useState('intro')
  const [error, setError] = useState(null)   // { kind: 'geo'|'api', code, text, retry }
  const [data, setData] = useState(null)
  const run = useRef(0)
  const headingRef = useRef(null)

  useEffect(() => () => { run.current += 1 }, []) // drop answers that land after leaving

  const load = useCallback(async (coords, id) => {
    setPhase('loading')
    try {
      const res = await fetchNearby({ lat: roundCoord(coords.latitude), lng: roundCoord(coords.longitude) }, token)
      if (run.current !== id) return
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
    setError(null)
    setData(null)
    const geo = typeof navigator !== 'undefined' ? navigator.geolocation : null
    if (!geo?.getCurrentPosition) {
      setError({ kind: 'geo', retry: false, ...geoErrorMessage('unsupported') })
      setPhase('error')
      return
    }
    setPhase('locating')
    geo.getCurrentPosition(
      (pos) => { if (run.current === id) load(pos.coords, id) },
      (err) => {
        if (run.current !== id) return
        setError({ kind: 'geo', retry: true, ...geoErrorMessage(err?.code) })
        setPhase('error')
      },
      GEO_OPTIONS,
    )
  }, [load])

  // Move focus to the result heading so keyboard and screen-reader users land on it
  useEffect(() => {
    if (phase === 'done' || phase === 'error') headingRef.current?.focus()
  }, [phase])

  const busy = phase === 'locating' || phase === 'loading'
  const sections = phase === 'done' ? nearbySections(data) : []
  const total = sections.reduce((n, s) => n + s.items.length, 0)
  const sources = phase === 'done' ? usableSources(data?.sources) : []
  const status = phase === 'locating' ? 'Finding your location…'
    : phase === 'loading' ? 'Looking for places near you…'
      : phase === 'done' ? `Found ${total} place${total === 1 ? '' : 's'} near ${data?.place?.name || 'you'}.`
        : phase === 'error' ? error?.text || '' : ''

  return (
    <main className="mx-auto max-w-4xl px-4 pb-16 pt-8 sm:px-6">
      <header className="mb-6 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="font-display text-2xl font-bold text-slate-900">Near me</h1>
          <p className="mt-1 max-w-xl text-sm text-slate-600">
            Places to see, eat, shop and stay around where you are right now.
          </p>
        </div>
        {(phase === 'done' || (phase === 'error' && error?.retry)) && (
          <button type="button" onClick={locate}
            className="inline-flex items-center gap-1.5 rounded-full border border-slate-300 bg-white px-3.5 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-500">
            <RefreshCw size={13} aria-hidden="true" /> {phase === 'done' ? 'Refresh' : 'Try again'}
          </button>
        )}
      </header>

      <p className="sr-only" role="status" aria-live="polite" data-testid="nearby-status">{status}</p>

      {phase === 'intro' && (
        <section aria-labelledby="nearby-intro" className="rounded-2xl border border-white/60 bg-white/90 px-6 py-8 text-center">
          <span className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-sky-50 text-sky-600">
            <MapPin size={22} aria-hidden="true" />
          </span>
          <h2 id="nearby-intro" className="mt-4 text-lg font-semibold text-slate-900">Use your location?</h2>
          <p className="mx-auto mt-2 max-w-md text-sm text-slate-600">
            Your browser will ask to share your location. We use it once, rounded to about 100 metres, to look up
            places around you on Google Maps. It isn’t saved, and neither are the results — they disappear when you
            leave this page.
          </p>
          <button type="button" onClick={locate}
            className="mt-5 inline-flex items-center gap-2 rounded-full bg-sky-600 px-5 py-2 text-sm font-semibold text-white hover:bg-sky-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-500">
            <LocateFixed size={15} aria-hidden="true" /> Use my location
          </button>
        </section>
      )}

      {busy && (
        <div aria-busy="true" data-testid="nearby-loading" className="space-y-8">
          <p className="flex items-center gap-2 text-sm text-slate-500">
            <Loader2 size={15} className="animate-spin" aria-hidden="true" />
            {phase === 'locating' ? 'Finding your location…' : 'Looking for places near you…'}
          </p>
          {phase === 'loading' && NEARBY_SECTIONS.map(s => <SkeletonSection key={s.id} title={s.title} />)}
        </div>
      )}

      {phase === 'error' && error && (
        <div role="alert" className="rounded-2xl border border-amber-200 bg-amber-50 px-5 py-5 text-amber-900">
          <h2 ref={headingRef} tabIndex={-1} className="flex items-center gap-2 font-semibold focus:outline-none">
            <AlertTriangle size={16} aria-hidden="true" />
            {error.kind === 'geo' ? 'We couldn’t get your location' : 'We couldn’t load places near you'}
          </h2>
          <p className="mt-1 text-sm">{error.text}</p>
          {error.retry && (
            <button type="button" onClick={locate}
              className="mt-3 rounded-full border border-amber-300 bg-white px-3 py-1 text-xs font-semibold hover:bg-amber-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-500">
              Try again
            </button>
          )}
        </div>
      )}

      {phase === 'done' && (
        <div className="space-y-8">
          <div>
            <h2 ref={headingRef} tabIndex={-1} className="font-display text-xl font-semibold text-slate-900 focus:outline-none">
              {placeLabel(data?.place) || 'Around you'}
            </h2>
            {data?.place?.distance_km != null && (
              <p className="mt-0.5 text-xs text-slate-500">
                About {Number(data.place.distance_km).toLocaleString('en-US', { maximumFractionDigits: 1 })} km from you
              </p>
            )}
          </div>

          {sections.map(s => (
            <section key={s.id} aria-labelledby={`nearby-${s.id}`} data-testid={`nearby-section-${s.id}`} className="space-y-3">
              <h2 id={`nearby-${s.id}`} className="text-sm font-semibold text-slate-700">
                {s.title} <span className="font-normal text-slate-400">({s.items.length})</span>
              </h2>
              {s.items.length > 0 ? (
                <ul className="grid gap-3 sm:grid-cols-2">
                  {s.items.map((item, i) => <ItemCard key={item.place_id || `${item.name}-${i}`} item={item} />)}
                </ul>
              ) : (
                <p className="rounded-xl bg-white/70 px-4 py-4 text-sm text-slate-500">{s.empty}</p>
              )}
            </section>
          ))}

          <footer className="space-y-2 border-t border-slate-200/70 pt-4 text-xs text-slate-500">
            <p data-testid="nearby-attribution">
              Places from <span className="font-medium text-slate-700" translate="no">{data?.attribution || 'Google Maps'}</span>
            </p>
            {sources.length > 0 && (
              <div>
                <h2 className="font-semibold text-slate-600">Sources</h2>
                <ul className="mt-1 space-y-0.5">
                  {sources.map(src => (
                    <li key={src.index}>
                      <a href={src.uri} target="_blank" rel="noopener noreferrer" className="text-sky-700 underline-offset-2 hover:underline">
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
