import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useJourney } from '../../hooks/useJourney'
import { useAuth } from '../../context/AuthContext'
import { addJournal, deleteJournal, listJournal } from '../../services/tripsApi'
import { enqueue } from '../../offline/outbox'
import { useOnline } from '../../offline/useOnline'
import { emit } from '../../telemetry/client'
import { fmtDate } from '../../i18n/format'
import JournalEntryForm from './JournalEntryForm'
import PlaceRatingsList from './PlaceRatingsList'

const newId = () => (globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`)

function tripDays(trip) {
  const { start_date: s, end_date: e } = trip || {}
  if (!s) return []
  const out = []
  const end = new Date(`${e || s}T12:00:00Z`)
  for (let d = new Date(`${s}T12:00:00Z`); d <= end && out.length < 366; d = new Date(d.getTime() + 864e5)) {
    const value = d.toISOString().slice(0, 10)
    out.push({ value, label: fmtDate(`${value}T12:00:00`, { day: 'numeric', month: 'short' }) || value })
  }
  return out
}

// Props: {trip, token}. The itinerary (for the places to rate) comes from
// trip.selections when present.
export default function Journal({ trip, token }) {
  const { enabled } = useJourney()
  const { user } = useAuth()
  const { t } = useTranslation('journal')
  const online = useOnline()
  const [entries, setEntries] = useState([])
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const inflight = useRef(false)
  const userId = user?.id
  const days = useMemo(() => tripDays(trip), [trip])
  const sel = trip?.selections || {}

  useEffect(() => {
    if (!enabled || !trip?.id) return undefined
    let live = true
    listJournal(token, trip.id).then((r) => { if (live) setEntries(r?.entries || []) }).catch(() => {})
    return () => { live = false }
  }, [enabled, token, trip?.id])

  const send = useCallback(async ({ body, mood, day }) => {
    const payload = { client_id: newId(), body }
    if (mood) payload.mood = mood
    if (day) payload.day = day
    const local = { id: `local-${payload.client_id}`, ...payload, mood: mood || null, day: day || null, pending: true }
    const queue = async () => {
      await enqueue(userId, { method: 'POST', path: `/trips/${trip.id}/journal`, body: payload, key: `journal:${trip.id}:${payload.client_id}` })
      setEntries((list) => [...list, local])
      emit('journal_action', { action: 'add', queued: true })
    }
    setError(null)
    if (!online) { await queue(); return true }
    try {
      const entry = await addJournal(token, trip.id, payload)
      setEntries((list) => [...list, entry])
      emit('journal_action', { action: 'add', queued: false })
      return true
    } catch (err) {
      if (err?.code === 'network') { await queue(); return true }
      setError(err?.message || t('error'))
      return false
    }
  }, [online, token, trip?.id, userId, t])

  // One add at a time: a double tap cannot send the text twice.
  const add = useCallback(async (values) => {
    if (inflight.current) return false
    inflight.current = true
    setBusy(true)
    try {
      return await send(values)
    } finally {
      inflight.current = false
      setBusy(false)
    }
  }, [send])

  const remove = useCallback(async (entry) => {
    if (entry.pending) return
    setError(null)
    try {
      await deleteJournal(token, trip.id, entry.id)
      setEntries((list) => list.filter((e) => e.id !== entry.id))
      emit('journal_action', { action: 'delete', queued: false })
    } catch (err) {
      if (err?.code === 'network') {
        await enqueue(userId, { method: 'DELETE', path: `/trips/${trip.id}/journal/${entry.id}`, key: `journal-del:${trip.id}:${entry.id}` })
        setEntries((list) => list.filter((e) => e.id !== entry.id))
        emit('journal_action', { action: 'delete', queued: true })
      } else setError(err?.message || t('error'))
    }
  }, [token, trip?.id, userId, t])

  if (!enabled || !trip) return null

  // Contract order: by day (no day last), then creation order.
  const byDay = new Map()
  entries.forEach((e, i) => {
    const d = e.day || ''
    if (!byDay.has(d)) byDay.set(d, [])
    byDay.get(d).push({ e, i })
  })
  const groups = [...byDay.keys()]
    .sort((a, b) => (a === b ? 0 : a === '' ? 1 : b === '' ? -1 : a < b ? -1 : 1))
    .map((d) => ({
      day: d || null,
      items: byDay.get(d)
        .sort((x, y) => String(x.e.created_at || '').localeCompare(String(y.e.created_at || '')) || x.i - y.i)
        .map((x) => x.e),
    }))

  return (
    <section className="space-y-6 text-slate-900" data-tid="journal">
      <h2 className="text-lg font-semibold">{t('title')}</h2>
      <JournalEntryForm onSubmit={add} days={days} busy={busy} />
      {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
      {groups.length === 0 ? (
        <p className="text-sm text-slate-600" data-tid="journal-empty">{t('empty')}</p>
      ) : groups.map((g) => (
        <div key={g.day || 'none'}>
          <h3 className="mb-2 text-sm font-medium text-slate-600">
            {g.day ? fmtDate(`${g.day}T12:00:00`, { weekday: 'short', day: 'numeric', month: 'short' }) : t('noDay')}
          </h3>
          <ul className="space-y-2">
            {g.items.map((e) => (
              <li key={e.id} className="rounded-lg border border-slate-200 p-3" data-tid={`journal-entry-${e.id}`}>
                <p className="whitespace-pre-wrap break-words">{e.body}</p>
                <div className="mt-2 flex items-center justify-between text-sm text-slate-600">
                  <span>{e.mood ? t(`mood.${e.mood}`) : ''}{e.pending ? ` ${t('pending')}` : ''}</span>
                  {!e.pending && (
                    <button type="button" onClick={() => remove(e)} data-tid={`journal-delete-${e.id}`}
                      className="min-h-[44px] px-3 text-red-700">{t('delete')}</button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </div>
      ))}
      <div>
        <h2 className="mb-2 text-lg font-semibold">{t('places.title')}</h2>
        <PlaceRatingsList
          trip={trip} token={token} userId={userId}
          itinerary={sel.itinerary || trip.itinerary} layout={sel.itinerary_layout} edits={sel.itinerary_edits}
        />
      </div>
    </section>
  )
}
