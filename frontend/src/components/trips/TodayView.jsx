import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Check, MapPin, Navigation as NavIcon, Share2 } from 'lucide-react'
import { useAuth } from '../../context/AuthContext'
import { useClientConfig } from '../../hooks/useClientConfig'
import { sharingEnabled } from '../../utils/share'
import ShareDialog from '../share/ShareDialog'
import { useJourney } from '../../hooks/useJourney'
import { useOnline } from '../../offline/useOnline'
import * as outbox from '../../offline/outbox'
import { checkIn, listCheckins, listPlaces, putPlace } from '../../services/tripsApi'
import { announceGame } from '../../game/announce'
import { emit } from '../../telemetry/client'
import { arrangeItinerary } from '../../utils/itineraryLayout'
import { scheduleDays, timeRange } from '../../utils/schedule'
import { dayIndex as dayIndexOf, localToday } from '../../utils/tripPhase'
import { placeKey } from '../../utils/placeKey'
import { directionsUrl, isApplePlatform } from '../../utils/mapsLinks'
import { nextUp, todaySlots } from '../../utils/today'
import { fmtDate } from '../../i18n/format'
import NextUpCard from './NextUpCard'
import PassportStamp from './PassportStamp'

const btn = 'inline-flex min-h-[44px] items-center justify-center gap-2 rounded-lg px-4 text-sm font-medium focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-500 disabled:opacity-50'
const primary = `${btn} bg-teal-700 hover:bg-teal-800 text-white`
const quiet = `${btn} border border-slate-300 bg-white text-slate-800 hover:bg-slate-50`

const reducedMotion = () => {
  try { return !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches } catch { return false }
}
const track = (action) => { try { emit('today_action', { action }) } catch { /* telemetry never blocks */ } }

export default function TodayView({ trip, token }) {
  const { t } = useTranslation('today')
  const { enabled } = useJourney()
  const { user } = useAuth()
  const navigate = useNavigate()
  const online = useOnline()
  const { config: clientConfig } = useClientConfig()
  const sharingV2 = sharingEnabled(clientConfig)
  const [shareOpen, setShareOpen] = useState(false)
  const userId = user?.id

  const [checked, setChecked] = useState(false)
  const [result, setResult] = useState(null) // the check-in answer
  const [streak, setStreak] = useState(null)
  const [visited, setVisited] = useState(() => new Set())
  const [queued, setQueued] = useState(() => new Set())
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)

  // Re-read the clock every minute so next-up and the day roll over.
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 60000)
    return () => clearInterval(id)
  }, [])
  const inFlight = useRef(new Set())
  const today = localToday(now)
  const idx = trip ? dayIndexOf(trip.start_date, trip.end_date, today) : null

  useEffect(() => {
    if (!enabled || !trip || !token || !online || idx === null) return undefined
    let live = true
    listCheckins(token, trip.id)
      .then((r) => {
        if (!live) return
        setChecked((r?.days || []).includes(today))
        setStreak(r?.streak ?? null)
      })
      .catch(() => {})
    listPlaces(token, trip.id)
      .then((r) => { if (live) setVisited(new Set((r?.places || []).filter((p) => p.visited).map((p) => p.place_key))) })
      .catch(() => {})
    return () => { live = false }
  }, [enabled, trip, token, online, idx, today])

  const source = trip?.selections || null
  const days = useMemo(() => {
    const it = source?.itinerary
    if (!it || !Array.isArray(it.days)) return []
    try {
      return scheduleDays(arrangeItinerary(it, source.itinerary_layout, source.itinerary_edits).days, source.itinerary_edits)
    } catch { return [] }
  }, [source])

  const slots = useMemo(() => todaySlots(days, idx), [days, idx])
  const upcoming = useMemo(() => nextUp(slots, now), [slots, now])

  const doCheckIn = useCallback(async () => {
    setBusy(true); setNote('')
    track('checkin')
    try {
      const res = await checkIn(token, trip.id, today)
      setResult(res); setChecked(true)
      if (res?.streak) setStreak(res.streak)
      announceGame(res?.game)
    } catch {
      setNote(t('checkinFailed'))
    } finally { setBusy(false) }
  }, [token, trip, today, t])

  const wentHere = useCallback(async (slot) => {
    const name = slot.activity
    const key = placeKey('activity', name)
    const body = { name, kind: 'activity', visited: true, day: today }
    if (Number.isFinite(slot.lat) && Number.isFinite(slot.lng)) { body.lat = slot.lat; body.lng = slot.lng }
    if (inFlight.current.has(key)) return
    inFlight.current.add(key)
    track('visited')
    try {
      if (!online) throw Object.assign(new Error('offline'), { code: 'network' })
      const res = await putPlace(token, trip.id, key, body)
      setVisited((s) => new Set(s).add(key))
      announceGame(res?.game)
    } catch (err) {
      if (err?.code !== 'network') { setNote(t('visitFailed')); return }
      await outbox.enqueue(userId, { method: 'PUT', path: `/trips/${trip.id}/places/${key}`, body, key: `place:${trip.id}:${key}` })
      setQueued((s) => new Set(s).add(key))
      setNote(t('queued'))
    } finally {
      inFlight.current.delete(key)
    }
  }, [online, token, trip, today, userId, t])

  const city = (days.find((d) => d.day_number === idx)?.city || trip?.destination || '').split(',')[0]
  const heading = t('dayIn', { day: idx, city })

  const share = useCallback(async () => {
    track('status_share')
    if (sharingV2) { setShareOpen(true); return }
    const text = heading
    try {
      if (navigator.share) await navigator.share({ text })
      else { await navigator.clipboard.writeText(text); setNote(t('copied')) }
    } catch { /* cancelled */ }
  }, [heading, t, sharingV2])

  if (!enabled || !trip) return null

  if (idx === null) {
    return (
      <section data-tid="today-view" className="p-4 text-slate-700">
        <p data-tid="today-not-started">{t('startsOn', { date: trip.start_date ? fmtDate(new Date(`${trip.start_date}T12:00:00`)) : '—' })}</p>
      </section>
    )
  }

  return (
    <section data-tid="today-view" className="mx-auto max-w-2xl space-y-4 p-4 text-slate-900">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <h2 data-tid="today-heading" className="text-xl font-bold">{heading}</h2>
        <button type="button" data-tid="today-share" onClick={share} className={quiet}>
          <Share2 size={16} aria-hidden="true" />{t('shareStatus')}
        </button>
      </header>
      {sharingV2 && shareOpen && <ShareDialog kind="status" planId={trip.id} text={heading} onClose={() => setShareOpen(false)} />}

      <div className="flex flex-wrap items-center gap-3">
        <button type="button" data-tid="today-checkin" onClick={doCheckIn} disabled={busy || checked || !online} className={primary}>
          <Check size={16} aria-hidden="true" />{checked ? t('checkedIn') : t('checkIn')}
        </button>
        {streak && streak.current > 0 && (
          <span data-tid="today-streak" className="text-sm font-medium text-amber-800">
            {t('streak', { count: streak.current })}
          </span>
        )}
        {result?.new_country && (reducedMotion()
          ? <p data-tid="today-new-country" className="text-sm font-semibold text-rose-700">{t('newCountry', { code: result.country_code })}</p>
          : <PassportStamp code={result.country_code} city={result.city} />)}
      </div>

      <NextUpCard slot={upcoming} onDirections={() => track('next_up')} />

      {slots.length === 0 ? (
        <p data-tid="today-empty" className="text-sm text-slate-600">{t('noPlan')}</p>
      ) : (
        <ul className="space-y-2">
          {slots.map((slot, i) => {
            const key = placeKey('activity', slot.activity)
            const done = visited.has(key)
            return (
              <li key={slot.key || i} data-tid={`today-slot-${i}`} className="rounded-xl border border-slate-200 bg-white p-3">
                <p className="text-xs text-slate-600">{timeRange(slot)}</p>
                <p className="font-medium">{slot.activity}</p>
                <div className="mt-2 flex flex-wrap gap-2">
                  <a
                    data-tid={`today-directions-${i}`}
                    href={directionsUrl({ lat: slot.lat, lng: slot.lng, name: slot.activity }, { apple: isApplePlatform() })}
                    target="_blank"
                    rel="noopener noreferrer"
                    onClick={() => track('directions')}
                    className={quiet}
                  >
                    <NavIcon size={16} aria-hidden="true" />{t('directions')}
                  </a>
                  <button type="button" data-tid={`today-visited-${i}`} onClick={() => wentHere(slot)} disabled={done || queued.has(key)} className={quiet}>
                    <MapPin size={16} aria-hidden="true" />{done || queued.has(key) ? t('visited') : t('wentHere')}
                  </button>
                </div>
              </li>
            )
          })}
        </ul>
      )}

      <button type="button" data-tid="today-nearby" onClick={() => { track('nearby'); navigate('/nearby') }} className={quiet}>
        <MapPin size={16} aria-hidden="true" />{t('nearMe')}
      </button>

      <p role="status" data-tid="today-note" className="min-h-[1.25rem] text-sm text-slate-600">{note}</p>
    </section>
  )
}
