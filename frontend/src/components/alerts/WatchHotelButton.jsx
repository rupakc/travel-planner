import { useMemo, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { BellPlus, BellRing } from 'lucide-react'
import { useOptionalAuth } from '../../context/AuthContext'
import { useAlerts, usePriceWatchFor } from '../../context/AlertsContext'
import { hotelPreview, hotelWatchSpec, money } from '../../utils/hotelWatch'
import { priceWatchLink } from '../../utils/priceWatch'
import { loginPathFor } from '../../utils/returnPath'
import PriceWatchDialog from './PriceWatchDialog'

const STYLES = {
  // small text action on a hotel card or in the My Plan drawer
  inline: {
    idle: 'inline-flex items-center gap-1 rounded text-xs font-medium text-sky-700 hover:text-sky-900 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-500',
    on: 'inline-flex items-center gap-1 rounded text-xs font-medium text-emerald-700 hover:text-emerald-900 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-500',
    size: 12,
  },
  // the compact chat cards
  compact: {
    idle: 'inline-flex items-center gap-0.5 rounded text-[10px] font-medium text-sky-700 hover:text-sky-900 focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-500',
    on: 'inline-flex items-center gap-0.5 rounded text-[10px] font-medium text-emerald-700 hover:text-emerald-900 focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-500',
    size: 9,
  },
}

export const hotelWatchingLabel = (w) => {
  if (w.status === 'paused') return 'Watch paused'
  return w.last_price != null ? `Watching · ${money(w.last_price, w.currency)}` : 'Watching'
}

/**
 * "Watch price" on a hotel. Needs the stay's dates (from the search: check-in
 * on departure, check-out on return, or the city's nights on a multi-city
 * trip) and live prices on the server; otherwise renders nothing. Signed out
 * it leads to sign-in and back; once watched it reads "Watching · $398" and
 * opens that watch on the Alerts page.
 */
export default function WatchHotelButton({ hotel, searchData, variant = 'inline', source = 'results' }) {
  const { token } = useOptionalAuth()
  const { caps } = useAlerts()
  const spec = useMemo(() => hotelWatchSpec(hotel, searchData), [hotel, searchData])
  if (!caps.fareWatch || !spec) return null
  if (!token) return <SignInToWatch hotel={hotel} variant={variant} />
  return <ActiveHotelButton hotel={hotel} spec={spec} variant={variant} source={source} />
}

function SignInToWatch({ hotel, variant }) {
  const navigate = useNavigate()
  const location = useLocation()
  const style = STYLES[variant] || STYLES.inline
  return (
    <button type="button" className={style.idle} title="Sign in to watch this hotel’s price"
      aria-label={`Sign in to watch the price of ${hotel.name}`}
      onClick={(e) => { e.stopPropagation(); navigate(loginPathFor(location)) }}>
      <BellPlus size={style.size} aria-hidden="true" /> Watch price
    </button>
  )
}

function ActiveHotelButton({ hotel, spec, variant, source }) {
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [watch, setWatch] = usePriceWatchFor('hotel', spec)
  const style = STYLES[variant] || STYLES.inline
  const watching = watch && watch.status !== 'expired'

  const onClick = (e) => {
    e.stopPropagation()
    if (watching) navigate(priceWatchLink(watch))
    else setOpen(true)
  }
  // A picked suggestion is a different hotel: this card's own hotel stays unwatched
  const onWatched = (w, meta) => { if (!meta?.viaSuggestion) setWatch(w) }

  return (
    <>
      <button type="button" onClick={onClick} className={watching ? style.on : style.idle}
        aria-label={watching ? `${hotelWatchingLabel(watch)}, ${hotel.name} — open your alerts` : `Watch the price of ${hotel.name}`}
        title={watching ? 'Open this watch on your Alerts page' : 'Get told when this hotel’s price drops'}>
        {watching ? <BellRing size={style.size} aria-hidden="true" /> : <BellPlus size={style.size} aria-hidden="true" />}
        <span className="tabular-nums">{watching ? hotelWatchingLabel(watch) : 'Watch price'}</span>
      </button>
      {open && (
        // Clicks inside the (portalled) dialog must not reach the card's own onClick
        <span onClick={e => e.stopPropagation()}>
          <PriceWatchDialog kind="hotel" spec={spec} preview={hotelPreview(hotel, spec)} source={source}
            onClose={() => setOpen(false)} onWatched={onWatched} />
        </span>
      )}
    </>
  )
}
