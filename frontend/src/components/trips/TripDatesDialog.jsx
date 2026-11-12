import { useEffect, useId, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'
import { X, Loader2 } from 'lucide-react'
import { errorText } from '../../services/apiError'

// Start and end date of a trip. Empty fields clear the dates (the trip goes
// back to Dreaming); an empty end makes a one-day trip. `onSave({start_date,
// end_date})` resolves when saved, or rejects with an ApiError shown here.
export default function TripDatesDialog({ start, end, onSave, onClose }) {
  const { t } = useTranslation(['trip', 'errors'])
  const titleId = useId()
  const ref = useRef(null)
  const [from, setFrom] = useState(start ?? '')
  const [to, setTo] = useState(end ?? '')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  // Focus the first field; Escape closes; Tab stays inside; focus goes back.
  const onKey = useRef(null)
  onKey.current = (e) => {
    if (e.key === 'Escape') { onClose(); return }
    if (e.key !== 'Tab' || !ref.current) return
    const items = [...ref.current.querySelectorAll('button:not([disabled]), input:not([disabled])')]
    if (!items.length) return
    const first = items[0]
    const last = items[items.length - 1]
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus() }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus() }
  }
  useEffect(() => {
    const opener = document.activeElement
    ref.current?.querySelector('input')?.focus()
    return () => { if (opener && typeof opener.focus === 'function') opener.focus() }
  }, [])

  const save = async (startDate, endDate) => {
    if (startDate && endDate && endDate < startDate) {
      setError(t('errors:trip_dates_invalid'))
      return
    }
    setSaving(true); setError('')
    try {
      // An end without a start means nothing: both go.
      await onSave({ start_date: startDate || null, end_date: startDate ? (endDate || null) : null })
      onClose()
    } catch (err) {
      setError(errorText(t, err))
      setSaving(false)
    }
  }

  const field = 'mt-1 block w-full min-h-[44px] rounded-lg border border-gray-300 bg-white px-3 text-sm text-gray-900 focus:border-teal-600 focus:outline-none focus:ring-2 focus:ring-teal-600/30'

  return createPortal(
    <div className="fixed inset-0 z-[60] flex items-end justify-center sm:items-center sm:p-4" onKeyDown={(e) => onKey.current(e)}>
      <div className="absolute inset-0 bg-slate-900/40 backdrop-blur-[2px]" onClick={onClose} aria-hidden="true" />
      <form
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        data-tid="trip.datesDialog"
        onSubmit={(e) => { e.preventDefault(); save(from, to) }}
        className="relative w-full rounded-t-2xl bg-white p-5 shadow-xl sm:max-w-sm sm:rounded-2xl"
      >
        <div className="flex items-start justify-between gap-3">
          <h2 id={titleId} className="text-base font-semibold text-gray-900">{t('dates.title')}</h2>
          <button type="button" onClick={onClose} data-tid="trip.dates.close" aria-label={t('dates.cancel')}
            className="-m-2 flex h-11 w-11 items-center justify-center rounded-lg text-gray-500 hover:bg-gray-100 hover:text-gray-700">
            <X size={18} aria-hidden="true" />
          </button>
        </div>
        <label className="mt-3 block text-sm font-medium text-gray-700">
          {t('dates.start')}
          <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} data-tid="trip.dates.start" className={field} />
        </label>
        <label className="mt-3 block text-sm font-medium text-gray-700">
          {t('dates.end')}
          <input type="date" value={to} min={from || undefined} disabled={!from} onChange={(e) => setTo(e.target.value)}
            data-tid="trip.dates.end" aria-describedby={`${titleId}-end`} className={`${field} disabled:opacity-50`} />
          <span id={`${titleId}-end`} className="mt-1 block text-xs font-normal text-gray-500">{t('dates.endHint')}</span>
        </label>
        {error && <p role="alert" data-tid="trip.dates.error" className="mt-3 text-sm text-red-700">{error}</p>}
        <div className="mt-5 flex flex-wrap items-center justify-between gap-2">
          <button type="button" disabled={saving || (!start && !end)} onClick={() => save('', '')} data-tid="trip.dates.clear"
            className="min-h-[44px] rounded-lg px-3 text-sm font-medium text-gray-600 hover:bg-gray-100 disabled:opacity-40">
            {t('dates.clear')}
          </button>
          <div className="flex gap-2">
            <button type="button" onClick={onClose} data-tid="trip.dates.cancel"
              className="min-h-[44px] rounded-lg border border-gray-300 px-4 text-sm font-medium text-gray-700 hover:bg-gray-50">
              {t('dates.cancel')}
            </button>
            <button type="submit" disabled={saving} data-tid="trip.dates.save"
              className="flex min-h-[44px] items-center gap-1.5 rounded-lg bg-teal-700 px-4 text-sm font-semibold text-white hover:bg-teal-800 disabled:opacity-50">
              {saving && <Loader2 size={14} className="animate-spin motion-reduce:animate-none" aria-hidden="true" />}
              {t('dates.save')}
            </button>
          </div>
        </div>
      </form>
    </div>,
    document.body,
  )
}
