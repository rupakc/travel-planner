import { useCallback, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { ArrowLeft, CalendarDays, ChevronDown, PenLine, Trash2, WifiOff, Loader2 } from 'lucide-react'
import { fmtDate } from '../../i18n/format'
import { errorText } from '../../services/apiError'
import PhaseMenu from './PhaseMenu'
import TripDatesDialog from './TripDatesDialog'

const PHASE_CHIP = {
  dreaming: 'bg-violet-50 text-violet-800 border-violet-200',
  planning: 'bg-sky-50 text-sky-800 border-sky-200',
  ready: 'bg-amber-50 text-amber-800 border-amber-200',
  on_the_road: 'bg-teal-50 text-teal-800 border-teal-200',
  memories: 'bg-rose-50 text-rose-800 border-rose-200',
}

// 'YYYY-MM-DD' as a local calendar date (new Date('2027-04-01') is UTC midnight,
// which is the day before west of Greenwich).
function localDate(day) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(day ?? ''))
  return m ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])) : null
}

const DAY_MS = 86400000
function dayCount(start, end) {
  const s = localDate(start)
  const e = localDate(end) ?? s
  if (!s) return null
  return Math.max(1, Math.round((Date.UTC(e.getFullYear(), e.getMonth(), e.getDate()) - Date.UTC(s.getFullYear(), s.getMonth(), s.getDate())) / DAY_MS) + 1)
}

function dateRange(start, end) {
  const s = localDate(start)
  if (!s) return ''
  const e = localDate(end)
  const opts = { day: 'numeric', month: 'short', year: 'numeric' }
  if (!e || end === start) return fmtDate(s, opts)
  return `${fmtDate(s, opts)} – ${fmtDate(e, opts)}`
}

/**
 * The trip screen's header: title (rename inline), dates (change them in a
 * dialog), countdown or "Day n of N", the phase chip with its menu, Delete.
 * `offline`: the trip came from the saved pack, so it is read-only.
 * `onPatch(changes, action)` resolves with the updated trip or rejects with an ApiError.
 */
export default function TripHeader({ trip, offline = false, savedAt = null, onPatch, onDelete }) {
  const { t } = useTranslation(['trip', 'journey', 'errors'])
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const [datesOpen, setDatesOpen] = useState(false)
  const [error, setError] = useState('')

  const closeMenu = useCallback(() => setMenuOpen(false), [])

  const run = async (changes, action) => {
    setBusy(true); setError('')
    try {
      await onPatch(changes, action)
      return true
    } catch (err) {
      setError(errorText(t, err))
      return false
    } finally {
      setBusy(false)
    }
  }

  const startRename = () => { setDraft(trip.title || ''); setEditing(true); setError('') }
  const submitRename = async (e) => {
    e.preventDefault()
    const title = draft.trim()
    if (!title || title === trip.title) { setEditing(false); return }
    if (title.length > 80) { setError(t('errors:trip_title_invalid')); return }
    if (await run({ title }, 'rename')) setEditing(false)
  }

  const pick = async (phase) => {
    setMenuOpen(false)
    if (phase === trip.phase && trip.phase_source === 'manual') return
    await run({ phase }, 'phase_override')
  }
  const follow = async () => {
    setMenuOpen(false)
    await run({ phase: null }, 'phase_clear')
  }

  const phase = trip.phase || 'dreaming'
  const manual = trip.phase_source === 'manual'
  const range = dateRange(trip.start_date, trip.end_date)
  let when = null
  if (trip.day_index) when = t('journey:dayOf', { day: trip.day_index, count: dayCount(trip.start_date, trip.end_date) })
  else if (trip.days_to_start) when = t('journey:countdown', { count: trip.days_to_start })

  const iconBtn = 'flex h-11 w-11 shrink-0 items-center justify-center rounded-lg text-gray-500 hover:bg-gray-100 hover:text-gray-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-600'

  return (
    <header data-tid="trip.header" className="rounded-2xl border border-white/60 bg-white/80 p-4 shadow-sm backdrop-blur sm:p-5">
      <div className="flex items-center justify-between gap-2">
        <Link to="/trips" data-tid="trip.back"
          className="-ml-2 inline-flex min-h-[44px] items-center gap-1 rounded-lg px-2 text-sm font-medium text-teal-800 hover:bg-teal-50">
          <ArrowLeft size={16} aria-hidden="true" /> {t('allTrips')}
        </Link>
        {!offline && (
          <button type="button" onClick={onDelete} data-tid="trip.delete" aria-label={t('header.delete')} title={t('header.delete')}
            className={`${iconBtn} hover:bg-red-50 hover:text-red-700`}>
            <Trash2 size={18} aria-hidden="true" />
          </button>
        )}
      </div>

      {editing ? (
        <form onSubmit={submitRename} className="mt-1 flex flex-wrap items-center gap-2">
          <label className="sr-only" htmlFor="trip-title-input">{t('header.titleLabel')}</label>
          <input
            id="trip-title-input"
            data-tid="trip.titleInput"
            autoFocus
            value={draft}
            maxLength={80}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Escape') { e.preventDefault(); setEditing(false) } }}
            className="min-h-[44px] min-w-0 flex-1 rounded-lg border border-gray-300 bg-white px-3 font-display text-xl font-semibold text-gray-900 focus:border-teal-600 focus:outline-none focus:ring-2 focus:ring-teal-600/30"
          />
          <button type="submit" disabled={busy} data-tid="trip.titleSave"
            className="flex min-h-[44px] items-center gap-1.5 rounded-lg bg-teal-700 px-4 text-sm font-semibold text-white hover:bg-teal-800 disabled:opacity-50">
            {busy && <Loader2 size={14} className="animate-spin motion-reduce:animate-none" aria-hidden="true" />}
            {t('header.save')}
          </button>
          <button type="button" onClick={() => setEditing(false)} data-tid="trip.titleCancel"
            className="min-h-[44px] rounded-lg border border-gray-300 px-4 text-sm font-medium text-gray-700 hover:bg-gray-50">
            {t('header.cancel')}
          </button>
        </form>
      ) : (
        <div className="mt-1 flex items-start gap-1">
          <h1 className="min-w-0 break-words font-display text-2xl font-semibold leading-tight text-gray-900 sm:text-3xl">{trip.title}</h1>
          {!offline && (
            <button type="button" onClick={startRename} data-tid="trip.rename" aria-label={t('header.rename')} title={t('header.rename')} className={iconBtn}>
              <PenLine size={18} aria-hidden="true" />
            </button>
          )}
        </div>
      )}

      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-2 text-sm text-gray-600">
        <div className="relative">
          {offline ? (
            <span data-tid="trip.phase" className={`inline-flex min-h-[32px] items-center rounded-full border px-3 text-xs font-semibold ${PHASE_CHIP[phase] ?? PHASE_CHIP.dreaming}`}>
              {t(`journey:phases.${phase}`)}
            </span>
          ) : (
            <button
              type="button"
              data-tid="trip.phase"
              aria-haspopup="menu"
              aria-expanded={menuOpen}
              aria-label={t('header.phaseLabel', { phase: t(`journey:phases.${phase}`) })}
              disabled={busy}
              onClick={() => setMenuOpen((v) => !v)}
              className={`inline-flex min-h-[44px] items-center gap-1 rounded-full border px-3 text-xs font-semibold sm:min-h-[32px] ${PHASE_CHIP[phase] ?? PHASE_CHIP.dreaming} hover:brightness-95 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-600 disabled:opacity-60`}
            >
              {t(`journey:phases.${phase}`)}
              {manual && <span className="font-normal opacity-80">· {t('header.manual')}</span>}
              <ChevronDown size={14} aria-hidden="true" />
            </button>
          )}
          {menuOpen && (
            <PhaseMenu phase={phase} manual={manual} onPick={pick} onFollow={follow} onClose={closeMenu} />
          )}
        </div>

        <span className="inline-flex items-center gap-1.5" data-tid="trip.dates">
          <CalendarDays size={15} className="text-gray-400" aria-hidden="true" />
          {range || t('header.noDates')}
        </span>
        {when && <span data-tid="trip.when" className="font-semibold text-teal-800">{when}</span>}
        {!offline && (
          <button type="button" onClick={() => setDatesOpen(true)} data-tid="trip.editDates"
            className="min-h-[44px] rounded-lg px-2 text-sm font-medium text-teal-800 underline-offset-2 hover:underline sm:min-h-0">
            {range ? t('header.editDates') : t('header.addDates')}
          </button>
        )}
      </div>

      {offline && (
        <p data-tid="trip.offlineNote" className="mt-3 flex items-center gap-2 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-900">
          <WifiOff size={16} className="shrink-0" aria-hidden="true" />
          {savedAt
            ? t('offline.note', { date: fmtDate(savedAt, { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' }) })
            : t('offline.noteUndated')}
        </p>
      )}
      {error && <p role="alert" data-tid="trip.headerError" className="mt-2 text-sm text-red-700">{error}</p>}

      {datesOpen && (
        <TripDatesDialog
          start={trip.start_date}
          end={trip.end_date}
          onSave={(changes) => onPatch(changes, 'dates')}
          onClose={() => setDatesOpen(false)}
        />
      )}
    </header>
  )
}
