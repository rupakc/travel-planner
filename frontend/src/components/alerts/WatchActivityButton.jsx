import { useContext, useMemo, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { BellPlus, BellRing } from 'lucide-react'
import { useOptionalAuth } from '../../context/AuthContext'
import { useAlerts, usePriceWatchFor } from '../../context/AlertsContext'
import { loginPathFor } from '../../utils/returnPath'
import { priceWatchLink } from '../../utils/priceWatch'
import { activitySpec, activityWatchingLabel, ownWatch } from '../../utils/activityWatch'
import { ActivityTripContext } from './activityTripContext'
import { useAirportCities } from '../../hooks/useAirportCities'
import { withCityNames } from '../../utils/cityNames'
import PriceWatchDialog from './PriceWatchDialog'

const STYLES = {
  // small text action inside an activity card / My Plan row
  inline: {
    idle: 'inline-flex items-center gap-1 text-xs font-medium text-sky-700 hover:text-sky-900 focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-500 rounded',
    on: 'inline-flex items-center gap-1 text-xs font-medium text-emerald-700 hover:text-emerald-900 focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-500 rounded',
    size: 11,
  },
  // compact rows (chat): small text, but a comfortable hit area
  compact: {
    idle: 'inline-flex min-h-6 items-center gap-0.5 px-1 py-1 text-[10px] font-medium text-sky-700 hover:text-sky-900 focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-500 rounded',
    on: 'inline-flex min-h-6 items-center gap-0.5 px-1 py-1 text-[10px] font-medium text-emerald-700 hover:text-emerald-900 focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-500 rounded',
    size: 9,
  },
}

/**
 * "Watch price" on an activity: watches the GetYourGuide / Viator listing
 * Google shows for it. Hidden unless the server has live prices; signed out
 * it leads to sign-in and back; once watched it reads "Watching · from
 * $11.63 pp" and opens the watch on the Alerts page. City, travellers and
 * the itinerary day come from the surrounding trip (ActivityTripContext).
 */
export default function WatchActivityButton({ activity, variant = 'inline', source = 'results' }) {
  const { token } = useOptionalAuth()
  const { caps } = useAlerts()
  const trip = useContext(ActivityTripContext)
  // the search stores airport codes ("LIS"): watch the city ("Lisbon")
  const sd = trip?.searchData
  const name = useAirportCities([sd?.destination, ...(sd?.destinations || []), activity?.city])
  const spec = useMemo(() => name && activitySpec(
    activity?.city ? { ...activity, city: name(activity.city) } : activity,
    trip && { ...trip, searchData: withCityNames(trip.searchData, name) },
  ), [activity, trip, name])
  if (!caps.fareWatch || !spec) return null
  const style = STYLES[variant] || STYLES.inline
  if (!token) return <SignInToWatch style={style} />
  return <ActiveButton activity={activity} spec={spec} style={style} source={source} />
}

function SignInToWatch({ style }) {
  const location = useLocation()
  return (
    <Link to={loginPathFor(location)} onClick={e => e.stopPropagation()} className={style.idle}
      title="Sign in to get told when this activity’s price drops">
      <BellPlus size={style.size} aria-hidden="true" /> Watch price
    </Link>
  )
}

function ActiveButton({ activity, spec, style, source }) {
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [watch, setWatch] = usePriceWatchFor('activity', spec)
  const watching = watch && watch.status !== 'expired'
  const label = watching ? activityWatchingLabel(watch) : 'Watch price'
  const people = spec.travellers === 1 ? '1 traveller' : `${spec.travellers} travellers`

  const onClick = (e) => {
    e.stopPropagation()
    if (watching) navigate(priceWatchLink(watch))
    else setOpen(true)
  }

  return (
    <>
      <button type="button" onClick={onClick} className={watching ? style.on : style.idle}
        aria-label={watching ? `${label} — open your alerts` : `Watch the price of ${activity.name}`}
        title={watching ? 'Open this watch on your Alerts page' : 'Get told when this activity’s price drops'}>
        {watching ? <BellRing size={style.size} aria-hidden="true" /> : <BellPlus size={style.size} aria-hidden="true" />}
        <span className="tabular-nums">{label}</span>
      </button>
      {open && (
        <PriceWatchDialog kind="activity" spec={spec} source={source} unitLabel="per person"
          preview={{
            title: spec.name,
            subtitle: [spec.city, people].join(' · '),
            price: spec.estimate_price != null ? spec.estimate_price * spec.travellers : null,
            currency: 'USD',
          }}
          onClose={() => setOpen(false)}
          onWatched={(w, meta) => { const own = ownWatch(w, meta); if (own) setWatch(own) }} />
      )}
    </>
  )
}
