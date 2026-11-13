import { useCallback, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import RatingStars from './RatingStars'
import { listPlaces, putPlace } from '../../services/tripsApi'
import { placeKey } from '../../utils/placeKey'
import { arrangeItinerary } from '../../utils/itineraryLayout'
import { enqueue } from '../../offline/outbox'
import RejectedWrites, { useRejectedWrites } from '../offline/RejectedWrites'
import { useOnline } from '../../offline/useOnline'
import { emit } from '../../telemetry/client'
import { announceGame } from '../../game/announce'

// Places to rate: the itinerary's activities plus any visited place the
// server already holds. Telemetry carries the action, kind and stars only.
export function itineraryPlaces(itinerary, layout, edits) {
  if (!itinerary) return []
  const seen = new Set()
  const out = []
  for (const day of arrangeItinerary(itinerary, layout, edits).days || []) {
    for (const slot of day.slots || []) {
      const name = String(edits?.[slot.key]?.activity || slot.activity || '').trim()
      if (!name) continue
      const key = placeKey('activity', name)
      if (seen.has(key)) continue
      seen.add(key)
      out.push({ place_key: key, name, kind: 'activity', day: null, lat: slot.lat ?? null, lng: slot.lng ?? null })
    }
  }
  return out
}

export default function PlaceRatingsList({ trip, token, userId, itinerary, layout, edits }) {
  const rejected = useRejectedWrites(userId, trip?.id == null ? null : `/trips/${trip.id}/places`)
  const { t } = useTranslation('journal')
  const online = useOnline()
  const [saved, setSaved] = useState({})
  const [error, setError] = useState(null)

  useEffect(() => {
    let live = true
    listPlaces(token, trip.id)
      .then((r) => { if (live) setSaved(Object.fromEntries((r?.places || []).map((p) => [p.place_key, p]))) })
      .catch(() => {})
    return () => { live = false }
  }, [token, trip.id])

  const rows = useMemo(() => {
    const planned = itineraryPlaces(itinerary, layout, edits)
    const keys = new Set(planned.map((p) => p.place_key))
    const extra = Object.values(saved).filter((p) => p.visited && !keys.has(p.place_key))
    return [...planned, ...extra].map((p) => ({ ...p, ...(saved[p.place_key] || {}) }))
  }, [itinerary, layout, edits, saved])

  const save = useCallback(async (row, changes, props) => {
    const key = row.place_key
    const before = saved[key]
    // Full current state, so a queued write that replaces an earlier one loses nothing.
    const merged = { ...row, ...changes }
    const body = { name: merged.name, kind: merged.kind, visited: !!merged.visited, stars: merged.stars ?? null }
    for (const f of ['note', 'day', 'lat', 'lng']) if (merged[f] != null) body[f] = merged[f]
    setError(null)
    setSaved((s) => ({ ...s, [key]: merged }))
    const queue = async () => {
      await enqueue(userId, { method: 'PUT', path: `/trips/${trip.id}/places/${encodeURIComponent(key)}`, body, key: `place:${trip.id}:${key}` })
      emit('place_action', props)
    }
    if (!online) { await queue(); return }
    try {
      const r = await putPlace(token, trip.id, key, body)
      if (r?.place) setSaved((s) => ({ ...s, [key]: r.place }))
      if (r?.game) announceGame(r.game)
      emit('place_action', props)
    } catch (err) {
      if (err?.code === 'network') { await queue(); return }
      setSaved((s) => { const n = { ...s }; if (before) n[key] = before; else delete n[key]; return n })
      setError(err?.message || t('error'))
    }
  }, [online, token, trip.id, userId, t, saved])

  if (!rows.length) return <p className="text-sm text-slate-600" data-tid="places-empty">{t('places.empty')}</p>

  return (
    <>
    <RejectedWrites userId={userId} rows={rejected} />
    <ul className="divide-y divide-slate-200" data-tid="places-list">
      {error && <li role="alert" className="py-2 text-sm text-red-700">{error}</li>}
      {rows.map((row) => (
        <li key={row.place_key} className="flex flex-wrap items-center justify-between gap-2 py-2" data-tid={`place-${row.place_key}`}>
          <div className="min-w-0 flex-1">
            <div className="truncate text-slate-900">{row.name}</div>
            <label className="mt-1 inline-flex min-h-[44px] items-center gap-2 text-sm text-slate-700 sm:min-h-0">
              <input
                type="checkbox"
                checked={!!row.visited}
                onChange={(e) => save(row, { visited: e.target.checked }, {
                  action: e.target.checked ? 'visited' : 'unvisited', kind: row.kind, stars: row.stars || 0,
                })}
                data-tid={`place-visited-${row.place_key}`}
              />
              {t('places.visited')}
            </label>
          </div>
          <RatingStars
            name={`place-${row.place_key}`}
            groupLabel={row.name}
            value={row.stars ?? null}
            onChange={(n) => save(row, { stars: n }, { action: n ? 'rate' : 'unrate', kind: row.kind, stars: n || 0 })}
          />
        </li>
      ))}
    </ul>
    </>
  )
}
