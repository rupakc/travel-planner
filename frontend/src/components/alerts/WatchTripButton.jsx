import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { BellPlus, BellRing } from 'lucide-react'
import { useOptionalAuth } from '../../context/AuthContext'
import { useAlerts, usePriceWatchFor } from '../../context/AlertsContext'
import { computePlanCost } from '../../utils/planHelpers'
import { formatDateRange } from '../../utils/fareWatch'
import { priceWatchLink } from '../../utils/priceWatch'
import { isWatchablePlan, tripPreviewParts, tripWatchingLabel } from '../../utils/tripWatch'
import { useAirportCities } from '../../hooks/useAirportCities'
import PriceWatchDialog from './PriceWatchDialog'

const STYLES = {
  // small text action inside a card or the plan drawer
  inline: {
    idle: 'inline-flex items-center gap-1 text-xs font-medium text-sky-700 hover:text-sky-900 focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-500 rounded',
    on: 'inline-flex items-center gap-1 text-xs font-medium text-emerald-700 hover:text-emerald-900 focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-500 rounded',
    hint: 'text-xs text-gray-500',
    size: 12,
  },
  // text action on a dark modal header (PlanViewModal)
  onDark: {
    idle: 'inline-flex items-center gap-1 rounded text-xs font-medium text-white/90 hover:text-white hover:underline underline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white',
    on: 'inline-flex items-center gap-1 rounded text-xs font-semibold text-emerald-200 hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white',
    hint: 'text-xs text-white/80',
    size: 12,
  },
}

/**
 * "Watch whole trip" for a saved plan: one price for its flight, hotel,
 * activities and other costs. Hidden unless signed in with live prices on
 * the server; an unsaved plan (`plan` without an id) shows, with
 * `showHint`, "Save your plan to watch its price". Once watched it reads
 * "Watching · $2,140" and opens the watch on the Alerts page. `className`
 * goes on the wrapper, so spacing disappears with the button; `savedNote`
 * (the My Plan drawer) says the watch prices the saved plan.
 */
export default function WatchTripButton({ plan, showHint = false, variant = 'inline', className = '', ...rest }) {
  const { token } = useOptionalAuth()
  const { caps } = useAlerts()
  if (!token || !caps.fareWatch) return null
  if (!plan?.id) {
    return showHint ? <p className={`${STYLES[variant].hint} ${className}`}>Save your plan to watch its price</p> : null
  }
  if (!isWatchablePlan(plan)) return null
  return <div className={className}><ActiveTripButton plan={plan} variant={variant} {...rest} /></div>
}

function ActiveTripButton({ plan, variant, source = 'saved_plan', label = 'Watch whole trip', savedNote = false }) {
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const spec = useMemo(() => ({ plan_id: plan.id }), [plan.id])
  const [watch, setWatch] = usePriceWatchFor('trip', spec)
  const style = STYLES[variant] || STYLES.inline
  const watching = watch && watch.status !== 'expired'
  const sd = plan.search_data || {}
  const name = useAirportCities([sd.destination])
  const city = String(sd.destination || '').split(',')[0]

  const preview = {
    title: plan.name,
    subtitle: [name ? name(city) : city, sd.departure_date && formatDateRange(sd.departure_date, sd.return_date)]
      .filter(Boolean).join(' · '),
    parts: tripPreviewParts(plan.selections, sd),
    planTotal: computePlanCost(plan.selections, sd) || null,
  }
  // No target is suggested: the parts above are estimates until the first
  // live look, and an estimate never seeds the target
  preview.price = null

  const onClick = (e) => {
    e.stopPropagation()
    if (watching) navigate(priceWatchLink(watch))
    else setOpen(true)
  }

  return (
    <>
      <button type="button" onClick={onClick} className={watching ? style.on : style.idle}
        aria-label={watching ? `${tripWatchingLabel(watch)} — open your alerts` : undefined}
        title={watching ? 'Open this watch on your Alerts page' : 'Get told when this trip’s total price drops'}>
        {watching ? <BellRing size={style.size} aria-hidden="true" /> : <BellPlus size={style.size} aria-hidden="true" />}
        <span className="tabular-nums">{watching ? tripWatchingLabel(watch) : label}</span>
      </button>
      {savedNote && !watching && (
        <p className={`mt-0.5 ${style.hint}`}>Watches your saved plan — save any changes first.</p>
      )}
      {open && (
        <PriceWatchDialog kind="trip" spec={spec} preview={preview} source={source}
          onClose={() => setOpen(false)}
          onWatched={(w, meta) => { if (!meta?.viaSuggestion) setWatch(w) }} />
      )}
    </>
  )
}
