import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { fetchFareCalendar } from '../services/api'
import { axiosErrorDetail } from '../utils/httpError'
import { tripFromSearch } from '../utils/fareWatch'
import WatchFareButton from './alerts/WatchFareButton'
import {
  cheapestDeparture, dayOffset, dayParts, fareDelta, formatDay as dayLabel, formatDelta, formatTripRange as tripRangeLabel,
  formatUsd, priceInsightsChip,
} from '../utils/fareCalendar'

const CHIP_TONES = {
  low: 'bg-green-50 text-green-800 border-green-200',
  typical: 'bg-gray-50 text-gray-700 border-gray-200',
  high: 'bg-amber-50 text-amber-800 border-amber-200',
}

/** Google Flights' own low/typical/high verdict for the searched dates. */
export function PriceInsightsChip({ insights }) {
  const { t } = useTranslation('alerts')
  const chip = priceInsightsChip(insights)
  if (!chip) return null
  const range = insights.typical_price_range
  const hasRange = Array.isArray(range) && range.length === 2 && range.every(Number.isFinite)
  const text = t(`fare.level.${chip.level}`)
    + (hasRange ? ` · ${t('fare.typical', { low: formatUsd(range[0]), high: formatUsd(range[1]) })}` : '')
  return (
    <div data-level={chip.level}
      className={`mb-4 inline-flex flex-wrap items-center gap-x-1.5 rounded-full border px-3 py-1 text-xs font-medium ${CHIP_TONES[chip.level]}`}>
      <span>{text}</span>
      <span className="font-normal opacity-70">· Google Flights</span>
    </div>
  )
}

function FareCell({ entry, selected, isCheapest, onPick }) {
  const { t } = useTranslation('alerts')
  const isSelected = entry.is_selected
  const { weekday, date } = dayParts(entry.departure_date)
  const delta = isSelected ? '' : formatDelta(fareDelta(entry, selected))
  const tone = isCheapest
    ? 'border-emerald-300 bg-emerald-50 text-emerald-800'
    : 'border-gray-200 bg-white text-gray-700 hover:border-sky-300 hover:bg-sky-50'
  return (
    <button type="button" data-tid="fare-calendar.cell" data-testid="fare-cell" data-date={entry.departure_date}
      data-cheapest={String(isCheapest)} aria-current={isSelected ? 'date' : undefined}
      onClick={() => !isSelected && onPick(entry)}
      title={isSelected ? t('fare.yourDates') : t('fare.replanFor', { day: dayLabel(entry.departure_date) })}
      className={`flex min-w-0 flex-col items-center rounded-lg border px-1 py-2 text-center transition-colors ${tone} ${isSelected ? 'cursor-default ring-2 ring-sky-500 ring-offset-1' : 'cursor-pointer'}`}>
      <span className="text-[10px] uppercase tracking-wide text-gray-400">{weekday}</span>
      <span className="text-xs font-medium">{date}</span>
      <span className={`mt-1 text-sm font-bold ${entry.cheapest_usd == null ? 'text-gray-300' : ''}`}>
        {entry.cheapest_usd == null ? '—' : formatUsd(entry.cheapest_usd)}
      </span>
      <span className={`h-4 text-[10px] ${delta.startsWith('−') ? 'text-emerald-600' : 'text-gray-400'}`}>
        {isSelected ? t('fare.yours') : delta}
      </span>
    </button>
  )
}

/**
 * Opt-in strip of the cheapest real fare for departure dates ±3 days
 * (same trip length). Picking another date asks before re-planning.
 */
export default function FareCalendarStrip({ searchData, token, onReplan, load = fetchFareCalendar }) {
  const { t } = useTranslation('alerts')
  const [state, setState] = useState({ status: 'loading', data: null, error: null })
  const [attempt, setAttempt] = useState(0)
  const [pending, setPending] = useState(null)

  useEffect(() => {
    let cancelled = false
    setState({ status: 'loading', data: null, error: null })
    load(searchData, token)
      .then(data => { if (!cancelled) setState({ status: 'done', data, error: null }) })
      .catch(err => {
        if (!cancelled) setState({ status: 'error', data: null, error: { detail: axiosErrorDetail(err).detail } })
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
    <section aria-label={t('fare.section')} className="mb-4 rounded-xl border border-gray-200 bg-gray-50/60 p-3">
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-x-3">
        <h4 className="text-xs font-semibold text-gray-700">{t('fare.section')}</h4>
        <p className="text-[11px] text-gray-400">{t('fare.hint')}</p>
        {state.status === 'done' && dates.length > 0 && (
          <span className="ml-auto">
            <WatchFareButton variant="inline" label={t('fare.watchDates')} trip={tripFromSearch(searchData)} defaultFlexible
              price={selected?.cheapest_usd ?? null} source="fare_calendar" />
          </span>
        )}
      </div>

      {state.status === 'loading' && (
        <div aria-busy="true" className="grid grid-cols-7 gap-1">
          {Array.from({ length: 7 }, (_, i) => <div key={i} className="h-[74px] animate-pulse rounded-lg bg-gray-200/70" />)}
        </div>
      )}

      {state.status === 'error' && (
        <div role="alert" className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          <span>{state.error?.detail || t('fare.error')}</span>
          <button type="button" data-tid="fare-calendar.retry" onClick={() => setAttempt(a => a + 1)}
            className="rounded-full border border-amber-300 bg-white px-3 py-1 font-semibold hover:bg-amber-100">{t('ui.retry')}</button>
        </div>
      )}

      {state.status === 'done' && dates.length === 0 && (
        <p className="text-xs text-gray-500">{t('fare.none')}</p>
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
          <span>{t('fare.replanPrompt', { range: tripRangeLabel(pending.departure_date, pending.return_date) })}</span>
          <span className="flex gap-2">
            <button type="button" data-tid="fare-calendar.cancel" onClick={() => setPending(null)}
              className="rounded-full border border-gray-300 bg-white px-3 py-1 font-medium text-gray-600 hover:bg-gray-50">{t('ui.cancel')}</button>
            <button type="button" data-tid="fare-calendar.replan" onClick={confirm}
              className="rounded-full bg-sky-600 px-3 py-1 font-semibold text-white hover:bg-sky-700">{t('fare.replan')}</button>
          </span>
        </div>
      )}
    </section>
  )
}
