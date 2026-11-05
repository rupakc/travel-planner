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

// Notices shared by every kind of watch (ended / paused): an activity's
// shows the activity icon; everything else, fares included, is unchanged.
const SHARED_NOTICES = new Set(['watch_expired', 'watch_error'])

export function kindOf(kind, data = null) {
  const base = ALERT_KINDS[kind] || ALERT_KINDS.watch_expired
  if (SHARED_NOTICES.has(kind) && data?.watch_kind === 'activity') {
    return { ...base, Icon: ALERT_KINDS.activity_drop.Icon }
  }
  return base
}

/** Keeps a price delta such as "(−$70)" or "(−€1.73)" on one line when a title wraps. */
export function keepDeltaTogether(text) {
  return typeof text === 'string' ? text.replace(/([−-])(?=[A-Z]{0,3}[$€£¥₹])/g, '$1⁠') : text
}
