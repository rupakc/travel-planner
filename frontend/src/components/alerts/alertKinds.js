import {
  AlertTriangle, BedDouble, CalendarDays, CalendarX, Luggage, Sparkles, Target, Ticket, TrendingDown,
} from 'lucide-react'

/** Icon, colour and action wording for each notification kind. */
export const ALERT_KINDS = {
  fare_drop:         { Icon: TrendingDown, tone: 'text-emerald-700 bg-emerald-50', action: 'See fare' },
  fare_target:       { Icon: Target, tone: 'text-emerald-700 bg-emerald-50', action: 'See fare' },
  fare_low_level:    { Icon: Sparkles, tone: 'text-sky-700 bg-sky-50', action: 'See fare' },
  fare_cheaper_date: { Icon: CalendarDays, tone: 'text-sky-700 bg-sky-50', action: 'See dates' },
  hotel_drop:        { Icon: BedDouble, tone: 'text-emerald-700 bg-emerald-50', action: 'See hotel' },
  hotel_target:      { Icon: BedDouble, tone: 'text-emerald-700 bg-emerald-50', action: 'See hotel' },
  activity_drop:     { Icon: Ticket, tone: 'text-emerald-700 bg-emerald-50', action: 'See activity' },
  activity_target:   { Icon: Ticket, tone: 'text-emerald-700 bg-emerald-50', action: 'See activity' },
  trip_drop:         { Icon: Luggage, tone: 'text-emerald-700 bg-emerald-50', action: 'See trip' },
  trip_target:       { Icon: Luggage, tone: 'text-emerald-700 bg-emerald-50', action: 'See trip' },
  watch_expired:     { Icon: CalendarX, tone: 'text-slate-500 bg-slate-100', action: 'View' },
  watch_error:       { Icon: AlertTriangle, tone: 'text-amber-700 bg-amber-50', action: 'Retry' },
}

// watch_expired / watch_error are shared by every watch kind: only trip
// watches (data.watch_kind === 'trip') get trip wording; fares keep theirs.
const TRIP_SHARED = {
  watch_expired: { ...ALERT_KINDS.watch_expired, action: 'See trip' },
  watch_error: { ...ALERT_KINDS.watch_error, action: 'Check trip' },
}

/** Style and action wording for a notification (`data` picks per-kind wording). */
export const kindOf = (kind, data = null) =>
  (data?.watch_kind === 'trip' && TRIP_SHARED[kind]) || ALERT_KINDS[kind] || ALERT_KINDS.watch_expired

/** Keeps a price delta such as "(−$70)" on one line when a title wraps. */
export function keepDeltaTogether(text) {
  return typeof text === 'string' ? text.replace(/([−-])\$/g, '$1⁠$') : text
}
