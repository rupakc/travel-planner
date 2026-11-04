import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { BellPlus, BellRing } from 'lucide-react'
import { useOptionalAuth } from '../../context/AuthContext'
import { useAlerts, useWatchFor } from '../../context/AlertsContext'
import { isWatchableTrip, watchingLabel } from '../../utils/fareWatch'
import { formatUsd } from '../../utils/fareCalendar'
import WatchDialog from './WatchDialog'

const STYLES = {
  // white-on-colour pill in a section header (next to Fare calendar / Filters)
  header: {
    idle: 'flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold bg-white/20 hover:bg-white/30 backdrop-blur-sm transition-all border border-white/20',
    on: 'flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold bg-white text-sky-700 border border-white transition-all',
    size: 12,
  },
  // small text action inside a card
  inline: {
    idle: 'inline-flex items-center gap-1 text-xs font-medium text-sky-700 hover:text-sky-900',
    on: 'inline-flex items-center gap-1 text-xs font-medium text-emerald-700 hover:text-emerald-900',
    size: 12,
  },
  // outlined button matching the saved-plan card actions
  card: {
    idle: 'flex flex-1 items-center justify-center gap-1.5 py-1 bg-white border border-gray-300 rounded-md text-xs font-medium text-gray-700 hover:bg-sky-50 hover:border-sky-400 hover:text-sky-700 transition-colors',
    on: 'flex flex-1 items-center justify-center gap-1.5 py-1 bg-emerald-50 border border-emerald-300 rounded-md text-xs font-medium text-emerald-800 hover:bg-emerald-100 transition-colors',
    size: 11,
    short: true,
  },
  // text action on a dark modal header
  onDark: {
    idle: 'inline-flex items-center gap-1 text-xs font-medium text-white/90 hover:text-white hover:underline underline-offset-2',
    on: 'inline-flex items-center gap-1 text-xs font-semibold text-emerald-200 hover:text-white',
    size: 12,
  },
}

/**
 * "Watch this fare" entry point. Hidden unless the trip can be watched and
 * the server has live fares; once watched it reads "Watching · $412" and
 * opens the Alerts page at that watch.
 */
export default function WatchFareButton(props) {
  const { token } = useOptionalAuth()
  const { caps } = useAlerts()
  // Nothing (and no router / API use) unless the fare can be watched
  if (!token || !caps.fareWatch || !isWatchableTrip(props.trip)) return null
  return <ActiveWatchButton {...props} />
}

function ActiveWatchButton({ trip, price = null, insights = null, variant = 'inline', source = 'results', label = 'Watch fare', defaultFlexible = false }) {
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [watch, setWatch] = useWatchFor(trip)
  const style = STYLES[variant]
  const watching = watch && watch.status !== 'expired'
  const watchedText = watching && style.short
    ? (watch.last_price != null ? formatUsd(watch.last_price) : 'Watching')
    : watching && watchingLabel(watch)

  const onClick = (e) => {
    e.stopPropagation()
    if (watching) navigate(`/alerts?watch=${watch.id}`)
    else setOpen(true)
  }

  return (
    <>
      <button type="button" onClick={onClick} className={watching ? style.on : style.idle}
        aria-label={watching ? `${watchingLabel(watch)} — open your alerts` : undefined}
        title={watching ? 'Open this watch on your Alerts page' : 'Get told when this fare drops'}>
        {watching ? <BellRing size={style.size} /> : <BellPlus size={style.size} />}
        <span className="tabular-nums">{watching ? watchedText : label}</span>
      </button>
      {open && (
        <WatchDialog trip={trip} price={price} insights={insights} source={source} defaultFlexible={defaultFlexible}
          onClose={() => setOpen(false)} onWatched={setWatch} />
      )}
    </>
  )
}
