import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../../context/AuthContext'
import { createTrip, notifyTripsChanged } from '../../services/tripsApi'
import { emit } from '../../telemetry/client'

const field = 'mt-1 w-full min-h-[44px] rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900'

// Save an idea: a Dreaming trip with a title and an optional destination.
export default function CreateTripDialog({ onClose, onCreated }) {
  const { t } = useTranslation('trips')
  const { token } = useAuth()
  const [title, setTitle] = useState('')
  const [destination, setDestination] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const input = useRef(null)

  const onCloseRef = useRef(onClose)
  onCloseRef.current = onClose

  useEffect(() => { input.current?.focus() }, [])

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onCloseRef.current() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  async function submit(e) {
    e.preventDefault()
    const clean = title.trim()
    if (!clean || busy) return
    setBusy(true)
    setError(null)
    try {
      const body = { title: clean }
      if (destination.trim()) body.destination = destination.trim()
      const trip = await createTrip(token, body)
      emit('trip_action', { action: 'create' })
      notifyTripsChanged()
      onCreated(trip)
    } catch (err) {
      setError(err?.code === 'trip_title_invalid' ? t('create.titleInvalid') : t('create.failed'))
      setBusy(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <form
        role="dialog" aria-modal="true" aria-labelledby="trips-create-title" onSubmit={submit}
        data-tid="trips-create-dialog"
        className="w-full max-w-md rounded-2xl bg-white p-5 shadow-xl"
      >
        <h2 id="trips-create-title" className="text-lg font-semibold text-slate-900">{t('create.heading')}</h2>
        <label className="mt-3 block text-sm text-slate-700">
          {t('create.title')}
          <input
            ref={input} data-tid="trips-create-title" value={title} maxLength={80} required
            onChange={(e) => setTitle(e.target.value)} className={field}
          />
        </label>
        <label className="mt-3 block text-sm text-slate-700">
          {t('create.destination')}
          <input
            data-tid="trips-create-destination" value={destination} maxLength={120}
            onChange={(e) => setDestination(e.target.value)} className={field}
          />
        </label>
        {error && <p role="alert" data-tid="trips-create-error" className="mt-3 text-sm text-red-700">{error}</p>}
        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button" data-tid="trips-create-cancel" onClick={onClose}
            className="min-h-[44px] rounded-lg border border-slate-300 px-4 py-2 text-sm text-slate-800"
          >{t('create.cancel')}</button>
          <button
            type="submit" data-tid="trips-create-submit" disabled={busy || !title.trim()}
            className="min-h-[44px] rounded-lg bg-teal-700 px-4 py-2 text-sm font-medium text-white hover:bg-teal-800 disabled:opacity-50"
          >{t('create.save')}</button>
        </div>
      </form>
    </div>
  )
}
