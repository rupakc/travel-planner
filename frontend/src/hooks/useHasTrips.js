import { useEffect, useState } from 'react'
import { useAuth } from '../context/AuthContext'
import { useJourney } from './useJourney'
import { listTrips, TRIPS_CHANGED_EVENT } from '../services/tripsApi'

// Whether the signed-in user has at least one trip: with the journey on, `/`
// is the Trips hub only for them (everyone else gets Explore). Any failure, a
// network error included, counts as "no trips". Signed out or journey off:
// false, and no request.
//
// One module-level answer, keyed by the signed-in user id and shared by every
// caller (Layout, NavBar). It is dropped when the last caller unmounts, which
// is what RequireAuth does on sign-out, so the next sign-in (same or another
// user) asks again; a token refresh while mounted never does. The window
// event `voyager:trips-changed` (notifyTripsChanged() in services/tripsApi)
// asks again in place, keeping the previous answer until the new one lands.
let cache = { key: null, value: null }
let mounted = 0
const listeners = new Set()

export function _resetHasTripsForTests() {
  cache = { key: null, value: null }
  mounted = 0
}

const notify = () => listeners.forEach((l) => l())

function fetchFor(key, token, previous = null) {
  const entry = { key, value: previous, token }
  cache = entry
  listTrips(token)
    .then((data) => Array.isArray(data?.trips) && data.trips.length > 0)
    .catch(() => false)
    .then((has) => {
      if (cache !== entry) return // superseded (another user, a newer fetch, cleared)
      entry.value = has
      notify()
    })
}

function onTripsChanged() {
  if (cache.key !== null && cache.token) fetchFor(cache.key, cache.token, cache.value)
}

export function useHasTrips() {
  const { isAuthenticated, token, user } = useAuth()
  const { enabled } = useJourney()
  const key = isAuthenticated && token && enabled ? String(user?.id ?? user?.username ?? '') : null
  const [, rerender] = useState(0)

  // Mount bookkeeping and the change event.
  useEffect(() => {
    const l = () => rerender((n) => n + 1)
    listeners.add(l)
    if (mounted++ === 0) window.addEventListener(TRIPS_CHANGED_EVENT, onTripsChanged)
    return () => {
      listeners.delete(l)
      if (--mounted === 0) {
        window.removeEventListener(TRIPS_CHANGED_EVENT, onTripsChanged)
        cache = { key: null, value: null }
      }
    }
  }, [])

  useEffect(() => {
    if (key === null) return
    if (cache.key !== key) fetchFor(key, token)
    else cache.token = token // a refresh: keep the answer, use the new token next time
  }, [key, token])

  if (key === null) return { hasTrips: false, loading: false }
  const value = cache.key === key ? cache.value : null
  return { hasTrips: value, loading: value === null }
}
