import { useEffect, useState } from 'react'
import { useAuth } from '../context/AuthContext'
import { useJourney } from './useJourney'
import { listTrips } from '../services/tripsApi'

// Whether the signed-in user has at least one trip: with the journey on, `/`
// is the Trips hub only for them (everyone else gets Explore). Fetched once
// per sign-in and shared by every caller; any failure, a network error
// included, counts as "no trips". Signed out or journey off: false, no request.
let cache = { key: null, value: null, promise: null }

export function _resetHasTripsForTests() {
  cache = { key: null, value: null, promise: null }
}

function load(key, token) {
  if (cache.key !== key) {
    const entry = { key, value: null, promise: null }
    entry.promise = listTrips(token)
      .then((data) => Array.isArray(data?.trips) && data.trips.length > 0)
      .catch(() => false)
      .then((has) => { entry.value = has; return has })
    cache = entry
  }
  return cache
}

export function useHasTrips() {
  const { isAuthenticated, token, user } = useAuth()
  const { enabled } = useJourney()
  const key = isAuthenticated && token && enabled ? String(user?.id ?? user?.username ?? '') : null
  const [, rerender] = useState(0)

  useEffect(() => {
    // Signed out (or journey off): the next sign-in asks again.
    if (key === null) { if (!isAuthenticated) _resetHasTripsForTests(); return undefined }
    const entry = load(key, token)
    if (entry.value !== null) return undefined
    let live = true
    entry.promise.then(() => { if (live) rerender((n) => n + 1) })
    return () => { live = false }
    // The token is read only when the key changes: a refresh never refetches.
  }, [key])

  if (key === null) return { hasTrips: false, loading: false }
  const value = cache.key === key ? cache.value : null
  return { hasTrips: value, loading: value === null }
}
