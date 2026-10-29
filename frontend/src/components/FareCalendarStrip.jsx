import { useEffect, useState } from 'react'
import { fetchFareCalendar } from '../services/api'
import { axiosErrorDetail } from '../utils/httpError'
import {
  cheapestDeparture, dayOffset, fareDelta, formatDay, formatDelta, formatUsd,
  priceInsightsChip, replanPrompt,
} from '../utils/fareCalendar'

const ERROR_FALLBACK = "Couldn't load the fare calendar."

const CHIP_TONES = {
  low: 'bg-green-50 text-green-800 border-green-200',
  typical: 'bg-gray-50 text-gray-700 border-gray-200',
  high: 'bg-amber-50 text-amber-800 border-amber-200',
}

/** Google Flights' own low/typical/high verdict for the searched dates. */
export function PriceInsightsChip({ insights }) {
  const chip = priceInsightsChip(insights)
  if (!chip) return null
  return (
    <div data-level={chip.level}
      className={`mb-4 inline-flex flex-wrap items-center gap-x-1.5 rounded-full border px-3 py-1 text-xs font-medium ${CHIP_TONES[chip.level]}`}>
      <span>{chip.text}</span>
      <span className="font-normal opacity-70">· Google Flights</span>
    </div>
  )
}

function FareCell({ entry, selected, isCheapest, onPick }) {
  const isSelected = entry.is_selected
  const [weekday, ...date] = formatDay(entry.departure_date).split(' ')
  const delta = isSelected ? '' : formatDelta(fareDelta(entry, selected))
  const tone = isCheapest
    ? 'border-emerald-300 bg-emerald-50 text-emerald-800'
    : 'border-gray-200 bg-white text-gray-700 hover:border-sky-300 hover:bg-sky-50'
  return (
    <button type="button" data-testid="fare-cell" data-date={entry.departure_date}
      data-cheapest={String(isCheapest)} aria-current={isSelected ? 'date' : undefined}
      onClick={() => !isSelected && onPick(entry)}
      title={isSelected ? 'Your current dates' : `Re-plan for ${formatDay(entry.departure_date)}`}
      className={`flex min-w-0 flex-col items-center rounded-lg border px-1 py-2 text-center transition-colors ${tone} ${isSelected ? 'cursor-default ring-2 ring-sky-500 ring-offset-1' : 'cursor-pointer'}`}>
      <span className="text-[10px] uppercase tracking-wide text-gray-400">{weekday}</span>
      <span className="text-xs font-medium">{date.join(' ')}</span>
      <span className={`mt-1 text-sm font-bold ${entry.cheapest_usd == null ? 'text-gray-300' : ''}`}>
        {entry.cheapest_usd == null ? '—' : formatUsd(entry.cheapest_usd)}
      </span>
      <span className={`h-4 text-[10px] ${delta.startsWith('−') ? 'text-emerald-600' : 'text-gray-400'}`}>
        {isSelected ? 'Yours' : delta}
      </span>
    </button>
  )
}

/**
 * Opt-in strip of the cheapest real fare for departure dates ±3 days
 * (same trip length). Picking another date asks before re-planning.
 */
export default function FareCalendarStrip({ searchData, token, onReplan, load = fetchFareCalendar }) {
  const [state, setState] = useState({ status: 'loading', data: null, error: null })
  const [attempt, setAttempt] = useState(0)
  const [pending, setPending] = useState(null)

  useEffect(() => {
    let cancelled = false
    setState({ status: 'loading', data: null, error: null })
    load(searchData, token)
      .then(data => { if (!cancelled) setState({ status: 'done', data, error: null }) })
      .catch(err => {
        if (!cancelled) setState({ status: 'error', data: null, error: axiosErrorDetail(err).detail || ERROR_FALLBACK })
      })
    return () => { cancelled = true }
  }, [searchData, token, load, attempt])

  const dates = state.data?.dates || []
  const selected = dates.find(d => d.is_selected)
  const cheapest = cheapestDeparture(dates)

  const confirm = () => {
    const entry = pending
    setPending(null)
    onReplan({
      departure_date: entry.departure_date,
      return_date: entry.return_date,
      offset: dayOffset(searchData.departure_date, entry.departure_date),
    })
  }

  return (
    <section aria-label="Fare calendar" className="mb-4 rounded-xl border border-gray-200 bg-gray-50/60 p-3">
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-x-3">
        <h4 className="text-xs font-semibold text-gray-700">Fare calendar</h4>
        <p className="text-[11px] text-gray-400">Cheapest live fare by departure date · same trip length</p>
      </div>

      {state.status === 'loading' && (
        <div aria-busy="true" className="grid grid-cols-7 gap-1">
          {Array.from({ length: 7 }, (_, i) => <div key={i} className="h-[74px] animate-pulse rounded-lg bg-gray-200/70" />)}
        </div>
      )}

      {state.status === 'error' && (
        <div role="alert" className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          <span>{state.error}</span>
          <button type="button" onClick={() => setAttempt(a => a + 1)}
            className="rounded-full border border-amber-300 bg-white px-3 py-1 font-semibold hover:bg-amber-100">Retry</button>
        </div>
      )}

      {state.status === 'done' && dates.length === 0 && (
        <p className="text-xs text-gray-500">No nearby dates to compare.</p>
      )}

      {state.status === 'done' && dates.length > 0 && (
        <div className="grid grid-cols-7 gap-1">
          {dates.map(entry => (
            <FareCell key={entry.departure_date} entry={entry} selected={selected}
              isCheapest={entry.departure_date === cheapest} onPick={setPending} />
          ))}
        </div>
      )}

      {pending && (
        <div data-testid="fare-replan-confirm" className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-sky-200 bg-sky-50 px-3 py-2 text-xs text-sky-900">
          <span>{replanPrompt(pending.departure_date, pending.return_date)}</span>
          <span className="flex gap-2">
            <button type="button" onClick={() => setPending(null)}
              className="rounded-full border border-gray-300 bg-white px-3 py-1 font-medium text-gray-600 hover:bg-gray-50">Cancel</button>
            <button type="button" onClick={confirm}
              className="rounded-full bg-sky-600 px-3 py-1 font-semibold text-white hover:bg-sky-700">Re-plan</button>
          </span>
        </div>
      )}
    </section>
  )
}
