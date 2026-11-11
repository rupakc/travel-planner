// Trip Remix — one-click "what if" transforms of a search request, plus
// before/after metric snapshots so the user can compare the two plans.

import i18n from '../i18n'
import { fmtNumber } from '../i18n/format'

const tt = (key, opts) => i18n.t(`sections:${key}`, opts)
const DAY_MS = 86400000

function toDate(str) {
  if (!str) return null
  const d = new Date(`${str}T00:00:00`)
  return Number.isNaN(d.getTime()) ? null : d
}

function toISO(date) {
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}

function shiftDates(searchData, days) {
  const dep = toDate(searchData.departure_date)
  if (!dep) return {}
  const out = { departure_date: toISO(new Date(dep.getTime() + days * DAY_MS)) }
  const ret = toDate(searchData.return_date)
  if (ret) out.return_date = toISO(new Date(ret.getTime() + days * DAY_MS))
  return out
}

export const REMIX_PRESETS = [
  {
    id: 'week_later',
    emoji: '📅',
    apply: (sd) => shiftDates(sd, 7),
  },
  {
    id: 'half_budget',
    emoji: '💸',
    apply: (sd) =>
      sd.budget_usd ? { budget_usd: Math.round(sd.budget_usd / 2) } : {},
  },
  {
    id: 'luxe',
    emoji: '✨',
    apply: (sd) =>
      sd.budget_usd ? { budget_usd: Math.round(sd.budget_usd * 2) } : {},
  },
  {
    id: 'slower_pace',
    emoji: '🧘',
    apply: () => ({ pace: 'relaxed' }),
  },
  {
    id: 'long_weekend',
    emoji: '⚡',
    apply: (sd) => {
      const dep = toDate(sd.departure_date)
      if (!dep) return {}
      return { return_date: toISO(new Date(dep.getTime() + 3 * DAY_MS)) }
    },
  },
]

// label / description read at use time so they follow a language switch
for (const preset of REMIX_PRESETS) {
  Object.defineProperties(preset, {
    label: { get: () => tt(`remix.preset.${preset.id}.label`), enumerable: true },
    description: { get: () => tt(`remix.preset.${preset.id}.description`), enumerable: true },
  })
}

export function applyRemix(searchData, presetId) {
  const preset = REMIX_PRESETS.find((p) => p.id === presetId)
  if (!preset) return searchData
  const changes = preset.apply(searchData)
  if (!Object.keys(changes).length) return searchData
  return { ...searchData, ...changes }
}

// ---------------------------------------------------------------------------
// Metric snapshots for before/after comparison

function minFlightPrice(results) {
  const prices = (results?.flights?.results || [])
    .map((f) => Number(f.price_usd))
    .filter((p) => Number.isFinite(p) && p > 0)
  return prices.length ? Math.min(...prices) : null
}

function minHotelNightly(results) {
  const prices = (results?.hotels?.results || [])
    .map((h) => Number(h.price_per_night_usd))
    .filter((p) => Number.isFinite(p) && p > 0)
  return prices.length ? Math.min(...prices) : null
}

function itineraryTotal(results) {
  const total = Number(results?.itinerary?.total_estimated_cost_usd)
  return Number.isFinite(total) && total > 0 ? total : null
}

function poorWeatherDays(results) {
  const days = results?.weather?.days
  if (!Array.isArray(days)) return null
  return days.filter((d) => d?.is_poor).length
}

export function snapshotMetrics(results) {
  return {
    min_flight_usd: minFlightPrice(results),
    min_hotel_nightly_usd: minHotelNightly(results),
    itinerary_total_usd: itineraryTotal(results),
    poor_weather_days: poorWeatherDays(results),
  }
}

const METRIC_META = {
  min_flight_usd: { kind: 'usd', betterWhen: 'lower' },
  min_hotel_nightly_usd: { kind: 'usd', betterWhen: 'lower' },
  itinerary_total_usd: { kind: 'usd', betterWhen: 'lower' },
  poor_weather_days: { kind: 'count', betterWhen: 'lower' },
}

export function diffMetrics(before, after) {
  const rows = []
  for (const [key, meta] of Object.entries(METRIC_META)) {
    const b = before?.[key]
    const a = after?.[key]
    if (b == null || a == null) continue
    const delta = a - b
    rows.push({
      key,
      label: tt(`remix.metric.${key}`),
      kind: meta.kind,
      before: b,
      after: a,
      delta,
      direction: delta === 0 ? 'same' : delta < 0 ? 'down' : 'up',
      improved: delta === 0 ? null : meta.betterWhen === 'lower' ? delta < 0 : delta > 0,
    })
  }
  return rows
}

export function formatMetricValue(value, kind) {
  if (value == null) return '—'
  if (kind === 'usd') return fmtNumber(Math.round(value), { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })
  return fmtNumber(value)
}
