import { useEffect, useState } from 'react'

// /api/config is fetched once per page load and cached at module level. A 404
// (older backend) or a network error gives {}: every feature stays hidden.
let cached = null
let pending = null

export function loadClientConfig() {
  if (cached) return Promise.resolve(cached)
  if (!pending) {
    pending = fetch('/api/config')
      .then((r) => (r.ok ? r.json() : {}))
      .catch(() => ({}))
      .then((c) => { cached = c && typeof c === 'object' ? c : {}; return cached })
  }
  return pending
}

export function useClientConfig() {
  const [state, setState] = useState(() => ({ config: cached || {}, loaded: !!cached }))
  useEffect(() => {
    if (cached) return undefined
    let live = true
    loadClientConfig().then((config) => { if (live) setState({ config, loaded: true }) })
    return () => { live = false }
  }, [])
  return state
}

export const signupAvailable = (config) => config?.auth?.signup_available === true
export const resetAvailable = (config) => config?.auth?.password_reset_available === true
