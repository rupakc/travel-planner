import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  headers: { 'Content-Type': 'application/json' },
})

/**
 * Stream search results using a Web Worker so SSE parsing
 * happens off the main thread, keeping the UI smooth.
 * Returns a cleanup function that terminates the worker.
 */
export function streamSearch(searchData, onResult, onDone, onError, token = null) {
  // Vite exposes workers via `new URL(..., import.meta.url)` + `{ type: 'module' }`
  const worker = new Worker(
    new URL('../workers/sseWorker.js', import.meta.url),
    { type: 'module' }
  )

  worker.onmessage = ({ data }) => {
    if (data.type === '__error') {
      onError(new Error(data.message))
      worker.terminate()
    } else if (data.type === '__stream_end' || data.type === 'done') {
      onDone()
      worker.terminate()
    } else {
      onResult(data.type, data.data, data.source)
    }
  }

  worker.onerror = (e) => {
    onError(new Error(e.message || 'Worker error'))
    worker.terminate()
  }

  worker.postMessage({
    url: '/api/search',
    headers: {
      'Content-Type': 'application/json',
      // Auth is optional on /api/search — when present, the backend injects
      // the user's learned Taste Graph profile into agent prompts.
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(searchData),
  })

  return () => worker.terminate()
}

export async function searchFlightsFiltered(searchData, filters) {
  const payload = {
    origin: searchData.origin,
    destination: searchData.destination,
    departure_date: searchData.departure_date,
    return_date: searchData.return_date || null,
    interests: searchData.interests || [],
    nationality: searchData.nationality || '',
    residence_permits: searchData.residence_permits || [],
    existing_visas: searchData.existing_visas || [],
    budget_usd: searchData.budget_usd || null,
    num_travelers: searchData.num_travelers || 1,
    ...filters,
  }
  const res = await api.post('/flights/filtered', payload)
  return res.data
}

export async function searchHotelsFiltered(searchData, filters) {
  const payload = {
    origin: searchData.origin,
    destination: searchData.destination,
    departure_date: searchData.departure_date,
    return_date: searchData.return_date || null,
    interests: searchData.interests || [],
    nationality: searchData.nationality || '',
    residence_permits: searchData.residence_permits || [],
    existing_visas: searchData.existing_visas || [],
    budget_usd: searchData.budget_usd || null,
    num_travelers: searchData.num_travelers || 1,
    ...filters,
  }
  const res = await api.post('/hotels/filtered', payload)
  return res.data
}

export async function searchActivitiesFiltered(searchData, filters) {
  const payload = {
    origin: searchData.origin,
    destination: searchData.destination,
    departure_date: searchData.departure_date,
    return_date: searchData.return_date || null,
    interests: searchData.interests || [],
    nationality: searchData.nationality || '',
    residence_permits: searchData.residence_permits || [],
    existing_visas: searchData.existing_visas || [],
    budget_usd: searchData.budget_usd || null,
    num_travelers: searchData.num_travelers || 1,
    ...filters,
  }
  const res = await api.post('/activities/filtered', payload)
  return res.data
}

export async function discoverDestinations(data) {
  const res = await api.post('/discover', data)
  return res.data
}

export default api
