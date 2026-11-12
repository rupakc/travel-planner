import { useContext, useMemo } from 'react'
import { useAlertsV2 } from '../../hooks/useAlertsV2'
import { useAirportCities } from '../../hooks/useAirportCities'
import { withCityNames } from '../../utils/cityNames'
import { hotelWatchSpec } from '../../utils/hotelWatch'
import { activitySpec } from '../../utils/activityWatch'
import { formatDateRange, isWatchableTrip } from '../../utils/fareWatch'
import { isWatchablePlan } from '../../utils/tripWatch'
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

/**
 * `trip` is tripFromSearch(searchData) / tripFromPlan(plan). The spec is that very
 * trip object, exactly what the classic WatchDialog posts (`...trip`).
 * `onColour` wraps the button in a light pill so it reads on a coloured header.
 */
export function QuickWatchFare({ trip, planId = null, surface = 'results', onColour = false }) {
  const { on } = useAlertsV2()
  if (!on || !isWatchableTrip(trip)) return null
  const button = <QuickWatchButton kind="flight" title={`${trip.origin} → ${trip.destination}`}
    subtitle={formatDateRange(trip.departure_date, trip.return_date)} spec={{ ...trip }} planId={planId} surface={surface} />
  return onColour ? <span className="inline-flex flex-col rounded-full bg-white/95 px-1">{button}</span> : button
}

/** Whole-trip watch of a saved plan: the same `{ plan_id }` spec as WatchTripButton. */
export function QuickWatchTrip({ plan, surface = 'results' }) {
  const { on } = useAlertsV2()
  if (!on || !isWatchablePlan(plan)) return null
  return <QuickWatchButton kind="trip" title={plan.name || String(plan.id)} spec={{ plan_id: plan.id }}
    planId={plan.id} surface={surface} />
}
