/* Voyager service worker: the offline app shell.
 *
 * Registered only when a user saves an offline pack (never at app start).
 * It caches the app shell and the hashed /assets/* files listed in
 * /sw-assets.json (written by vite/swAssets.js); trip data lives in
 * IndexedDB, never here.
 *
 * - Navigations: network first, so a deploy shows up whenever the user is
 *   online; on a network failure, the cached /index.html.
 * - /assets/*: cache first, then the network.
 * - Everything else, /api/* included, is not intercepted.
 * - message {type: 'precache'}: fetch /sw-assets.json (no-store), cache every
 *   URL into voyager-shell-<version>, delete the other voyager-shell-*
 *   caches, reply {ok, bytes}.
 * - message {type: 'purge'}: delete every voyager-* cache, reply {ok: true}.
 *
 * Served by the Caddy SPA handle with Cache-Control: no-cache.
 */
'use strict'

const CACHE_PREFIX = 'voyager-'
const SHELL_PREFIX = 'voyager-shell-'
// Shell files that must be cached for the offline shell to work; the other
// shell entries (e.g. a manifest an older build lacks) are skipped if missing.
const REQUIRED = ['/index.html']
const PARALLEL = 6

self.addEventListener('install', () => { self.skipWaiting() })
self.addEventListener('activate', (event) => { event.waitUntil(self.clients.claim()) })

async function shellCache() {
  const names = (await caches.keys()).filter((n) => n.startsWith(SHELL_PREFIX))
  if (!names.length) return null
  return caches.open(names[names.length - 1])
}

async function fromShell(path) {
  const cache = await shellCache()
  return cache ? cache.match(path) : undefined
}

async function navigate(request) {
  try {
    return await fetch(request)
  } catch (err) {
    const cached = (await fromShell('/index.html')) || (await fromShell('/'))
    if (cached) return cached
    throw err
  }
}

async function asset(request) {
  const cached = await fromShell(new URL(request.url).pathname)
  return cached || fetch(request)
}

self.addEventListener('fetch', (event) => {
  const request = event.request
  if (request.method !== 'GET') return
  let url
  try { url = new URL(request.url) } catch { return }
  if (url.origin !== self.location.origin) return
  const path = url.pathname
  if (path.startsWith('/api/') || path === '/health' || path.startsWith('/health/')) return
  if (request.mode === 'navigate') { event.respondWith(navigate(request)); return }
  if (path.startsWith('/assets/')) event.respondWith(asset(request))
})

// A response a navigation can use: browsers refuse a cached `redirected`
// response for a navigation, so those are re-wrapped.
async function storable(response) {
  if (!response.redirected) return response
  const body = await response.blob()
  return new Response(body, { status: response.status, statusText: response.statusText, headers: response.headers })
}

async function precache() {
  const res = await fetch('/sw-assets.json', { cache: 'no-store' })
  if (!res.ok) throw new Error(`sw-assets.json ${res.status}`)
  const manifest = await res.json()
  const version = String(manifest.version || 'unknown').replace(/[^\w.+-]/g, '_')
  const name = SHELL_PREFIX + version
  const shell = Array.isArray(manifest.shell) ? manifest.shell : []
  const assets = Array.isArray(manifest.assets) ? manifest.assets : []
  const urls = [...new Set([...shell, ...assets])]
  const required = new Set([...REQUIRED, ...assets])
  const existed = (await caches.keys()).includes(name)
  const cache = await caches.open(name)
  let bytes = 0
  let ok = true

  const one = async (url) => {
    let response
    try { response = await fetch(url, { cache: 'no-cache' }) } catch { response = null }
    if (!response || !response.ok) {
      if (required.has(url)) ok = false
      return
    }
    const body = await response.clone().arrayBuffer()
    bytes += body.byteLength
    await cache.put(url, await storable(response))
  }
  for (let i = 0; i < urls.length; i += PARALLEL) {
    await Promise.all(urls.slice(i, i + PARALLEL).map(one))
  }

  if (!ok) {
    // keep whatever worked before; a half-filled new cache is useless
    if (!existed) await caches.delete(name)
    return { ok: false, bytes }
  }
  // the same version precached again: drop entries no longer listed
  const keep = new Set(urls)
  for (const req of await cache.keys()) {
    const path = new URL(req.url).pathname
    if (!keep.has(path)) await cache.delete(req)
  }
  for (const other of await caches.keys()) {
    if (other.startsWith(SHELL_PREFIX) && other !== name) await caches.delete(other)
  }
  return { ok: true, bytes }
}

async function purge() {
  for (const name of await caches.keys()) {
    if (name.startsWith(CACHE_PREFIX)) await caches.delete(name)
  }
  return { ok: true }
}

self.addEventListener('message', (event) => {
  const data = event.data || {}
  const port = event.ports && event.ports[0]
  const reply = (msg) => {
    try {
      if (port) port.postMessage(msg)
      else if (event.source) event.source.postMessage(msg)
    } catch (_) { /* the page went away */ }
  }
  let job = null
  if (data.type === 'precache') job = precache().catch(() => ({ ok: false, bytes: 0 }))
  else if (data.type === 'purge') job = purge().catch(() => ({ ok: false }))
  if (job) event.waitUntil(job.then(reply))
})
