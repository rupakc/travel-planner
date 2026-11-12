import { useEffect, useState } from 'react'

// /api/config is fetched once per page load and cached at module level. A 404
// (older backend) or another HTTP error gives {}: every feature stays hidden.
// The last good answer is also kept in localStorage (tp_config_cache), and a
// request that never got an answer (offline) uses it, so a reload in airplane
// mode keeps the journey shell (and the saved offline pack) on. A fresh
// answer always wins, e.g. features.offline_pack false.
const STORAGE_KEY = 'tp_config_cache'
let cached = null
let pending = null

const isObject = (c) => !!c && typeof c === 'object' && !Array.isArray(c)

function readStored() {
  try {
    const c = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null')
    return isObject(c) ? c : null
  } catch { return null }
}
function writeStored(c) {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(c)) } catch { /* private mode */ }
}
function dropStored() {
  try { localStorage.removeItem(STORAGE_KEY) } catch { /* private mode */ }
}

async function fetchConfig() {
  let r
  try {
    r = await fetch('/api/config')
  } catch {
    return readStored() || {} // no answer at all: the last good /config
  }
  if (!r.ok) { dropStored(); return {} }
  try {
    const c = await r.json()
    if (!isObject(c)) return {}
    writeStored(c)
    return c
  } catch { return {} }
}

export function loadClientConfig() {
  if (cached) return Promise.resolve(cached)
  if (!pending) {
    pending = fetchConfig().then((c) => { cached = isObject(c) ? c : {}; return cached })
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

// `features.<name> === true` in /config. An older backend's /config has no
// `accounts`/`game` flags (or 404s), so their endpoints are never probed:
// no 404 noise in devtools on every load.
export const featureOn = (config, name) => config?.features?.[name] === true
