import {
  AlertTriangle, BedDouble, CalendarDays, CalendarX, Luggage, PlaneTakeoff, Sun, Sparkles, Target, Ticket, TrendingDown,
} from 'lucide-react'
import i18n from '../../i18n'

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
  trip_t30:          { Icon: CalendarDays, tone: 'text-sky-700 bg-sky-50', action: 'Open trip' },
  trip_t7:           { Icon: Luggage, tone: 'text-sky-700 bg-sky-50', action: 'Open trip' },
  trip_t1:           { Icon: PlaneTakeoff, tone: 'text-sky-700 bg-sky-50', action: 'Open trip' },
  trip_morning:      { Icon: Sun, tone: 'text-amber-700 bg-amber-50', action: 'Open today' },
  price_digest:      { Icon: CalendarDays, tone: 'text-sky-700 bg-sky-50', action: 'View' },
  watch_expired:     { Icon: CalendarX, tone: 'text-slate-500 bg-slate-100', action: 'View' },
  watch_error:       { Icon: AlertTriangle, tone: 'text-amber-700 bg-amber-50', action: 'Retry' },
}

export const kindOf = (kind) => ALERT_KINDS[kind] || ALERT_KINDS.watch_expired

// The `action` strings above double as identifiers (callers compare them);
// this maps each to its catalogue entry so what the traveller reads is localized.
const ACTION_KEYS = {
  'See fare': 'kinds.seeFare',
  'See dates': 'kinds.seeDates',
  'See hotel': 'kinds.seeHotel',
  'See activity': 'kinds.seeActivity',
  'See trip': 'kinds.seeTrip',
  'Check trip': 'kinds.checkTrip',
  'Open trip': 'kinds.openTrip',
  'Open today': 'kinds.openToday',
  View: 'kinds.view',
  Retry: 'kinds.retry',
}
export const actionText = (action) => (ACTION_KEYS[action] ? i18n.t(`alerts:${ACTION_KEYS[action]}`) : action)

// Notices shared by every kind of watch (ended / paused).
const SHARED_NOTICES = new Set(['watch_expired', 'watch_error'])

/**
 * Icon, colour and action for one notification. The shared notices
 * (watch_expired / watch_error) read per watch kind — a hotel's ended watch
 * says "See hotel", an activity's ended watch shows the activity icon (its
 * paused notice keeps the warning icon), a trip's
 * say "See trip" / "Check trip"; fare notices keep kindOf's wording.
 */
export function alertKindFor(n) {
  const base = kindOf(n?.kind)
  if (!SHARED_NOTICES.has(n?.kind)) return base
  const watchKind = n?.data?.watch_kind
  if (watchKind === 'hotel' && n.kind === 'watch_expired') return { ...base, action: 'See hotel' }
  // an ended activity watch shows the ticket; a paused one keeps the warning
  if (watchKind === 'activity' && n.kind === 'watch_expired') return { ...base, Icon: ALERT_KINDS.activity_drop.Icon }
  if (watchKind === 'trip') return { ...base, action: n.kind === 'watch_expired' ? 'See trip' : 'Check trip' }
  return base
}

/** Keeps a price delta such as "(−$70)" or "(−€1.73)" on one line when a title wraps. */
export function keepDeltaTogether(text) {
  return typeof text === 'string' ? text.replace(/([−-])(?=[A-Z]{0,3}[$€£¥₹])/g, '$1⁠') : text
}
