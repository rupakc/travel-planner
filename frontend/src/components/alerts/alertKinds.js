import {
  AlertTriangle, CalendarDays, CalendarX, Sparkles, Target, TrendingDown,
} from 'lucide-react'

/** Icon, colour and action wording for each notification kind. */
export const ALERT_KINDS = {
  fare_drop:         { Icon: TrendingDown, tone: 'text-emerald-700 bg-emerald-50', action: 'See fare' },
  fare_target:       { Icon: Target, tone: 'text-emerald-700 bg-emerald-50', action: 'See fare' },
  fare_low_level:    { Icon: Sparkles, tone: 'text-sky-700 bg-sky-50', action: 'See fare' },
  fare_cheaper_date: { Icon: CalendarDays, tone: 'text-sky-700 bg-sky-50', action: 'See dates' },
  watch_expired:     { Icon: CalendarX, tone: 'text-slate-500 bg-slate-100', action: 'View' },
  watch_error:       { Icon: AlertTriangle, tone: 'text-amber-700 bg-amber-50', action: 'Retry' },
}

export const kindOf = (kind) => ALERT_KINDS[kind] || ALERT_KINDS.watch_expired

/** Keeps a price delta such as "(−$70)" on one line when a title wraps. */
export function keepDeltaTogether(text) {
  return typeof text === 'string' ? text.replace(/([−-])\$/g, '$1⁠$') : text
}
