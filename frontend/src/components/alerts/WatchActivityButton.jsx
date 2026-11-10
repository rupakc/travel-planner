import { useContext, useMemo, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { BellPlus, BellRing } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useOptionalAuth } from '../../context/AuthContext'
import { useAlerts, usePriceWatchFor } from '../../context/AlertsContext'
import { loginPathFor } from '../../utils/returnPath'
import { priceWatchLink } from '../../utils/priceWatch'
import {
  activitySpec, activityWatchingLabel as watchingLabel, ownWatch,
} from '../../utils/activityWatch'
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
  const { t } = useTranslation('alerts')
  const location = useLocation()
  return (
    <Link to={loginPathFor(location)} data-tid="alerts.watch-activity-signin" onClick={e => e.stopPropagation()} className={style.idle}
      title={t('btn.signInActivity')}>
      <BellPlus size={style.size} aria-hidden="true" /> {t('btn.watchPrice')}
    </Link>
  )
}

function ActiveButton({ activity, spec, style, source }) {
  const { t } = useTranslation('alerts')
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [watch, setWatch] = usePriceWatchFor('activity', spec)
  const watching = watch && watch.status !== 'expired'
  const label = watching ? watchingLabel(watch) : t('btn.watchPrice')
  const people = t('act.people', { count: spec.travellers })

  const onClick = (e) => {
    e.stopPropagation()
    if (watching) navigate(priceWatchLink(watch))
    else setOpen(true)
  }

  return (
    <>
      <button type="button" data-tid="alerts.watch-activity" onClick={onClick} className={watching ? style.on : style.idle}
        aria-label={watching ? t('btn.openAria', { label }) : t('btn.watchActivityAria', { name: activity.name })}
        title={watching ? t('btn.openWatch') : t('btn.activityTitle')}>
        {watching ? <BellRing size={style.size} aria-hidden="true" /> : <BellPlus size={style.size} aria-hidden="true" />}
        <span className="tabular-nums">{label}</span>
      </button>
      {open && (
        <PriceWatchDialog kind="activity" spec={spec} source={source} unitLabel={t('unit.person')}
          preview={{
            title: spec.name,
            subtitle: [spec.city, people].join(' · '),
            // the AI estimate is no live price: it never seeds the target
            // (the dialog body shows it, labelled)
            price: null,
            currency: 'USD',
          }}
          onClose={() => setOpen(false)}
          onWatched={(w, meta) => { const own = ownWatch(w, meta); if (own) setWatch(own) }} />
      )}
    </>
  )
}
