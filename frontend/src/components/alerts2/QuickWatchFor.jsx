import { useContext, useMemo } from 'react'
import { useAlertsV2 } from '../../hooks/useAlertsV2'
import { useAirportCities } from '../../hooks/useAirportCities'
import { withCityNames } from '../../utils/cityNames'
import { hotelWatchSpec } from '../../utils/hotelWatch'
import { activitySpec } from '../../utils/activityWatch'
import { formatDateRange, isWatchableTrip } from '../../utils/fareWatch'
import { ActivityTripContext } from '../alerts/activityTripContext'
import QuickWatchButton from './QuickWatchButton'

// One-tap watch for a card. Each builds its spec with the very builders the
// classic "Watch price" dialog buttons use (same city naming included), so a
// quick watch matches the dialog's watch exactly. Rendered only when price
// alerts 2.0 is on; QuickWatchButton itself hides without live prices.

export function QuickWatchHotel({ hotel, searchData, planId = null, surface = 'results' }) {
  const { on } = useAlertsV2()
  if (!on) return null
  return <HotelInner hotel={hotel} searchData={searchData} planId={planId} surface={surface} />
}

function HotelInner({ hotel, searchData, planId, surface }) {
  const name = useAirportCities([searchData?.destination, ...(searchData?.destinations || []), hotel?.city])
  const spec = useMemo(() => name && hotelWatchSpec(
    hotel?.city ? { ...hotel, city: name(hotel.city) } : hotel, withCityNames(searchData, name),
  ), [hotel, searchData, name])
  if (!spec) return null
  return <QuickWatchButton kind="hotel" title={hotel.name} subtitle={formatDateRange(spec.check_in, spec.check_out)}
    spec={spec} planId={planId} surface={surface} />
}

export function QuickWatchActivity({ activity, planId = null, surface = 'results' }) {
  const { on } = useAlertsV2()
  if (!on) return null
  return <ActivityInner activity={activity} planId={planId} surface={surface} />
}

function ActivityInner({ activity, planId, surface }) {
  const trip = useContext(ActivityTripContext)
  const sd = trip?.searchData
  const name = useAirportCities([sd?.destination, ...(sd?.destinations || []), activity?.city])
  const spec = useMemo(() => name && activitySpec(
    activity?.city ? { ...activity, city: name(activity.city) } : activity,
    trip && { ...trip, searchData: withCityNames(trip.searchData, name) },
  ), [activity, trip, name])
  if (!spec) return null
  return <QuickWatchButton kind="activity" title={activity.name} subtitle={spec.city}
    spec={spec} planId={planId} surface={surface} />
}

/** `trip` is tripFromSearch(searchData): a flight spec holds the fare-watch trip fields. */
export function QuickWatchFare({ trip, planId = null, surface = 'results' }) {
  const { on } = useAlertsV2()
  const spec = useMemo(() => (trip && {
    origin: trip.origin, destination: trip.destination, departure_date: trip.departure_date,
    return_date: trip.return_date || null, num_travelers: trip.num_travelers || 1,
  }), [trip])
  if (!on || !isWatchableTrip(trip)) return null
  return <QuickWatchButton kind="flight" title={`${trip.origin} → ${trip.destination}`}
    subtitle={formatDateRange(trip.departure_date, trip.return_date)} spec={spec} planId={planId} surface={surface} />
}
