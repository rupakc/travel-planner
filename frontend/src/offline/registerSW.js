// Service-worker control. The worker (/sw.js) is never registered at app
// start: only when a user saves an offline pack (Task 22 calls
// ensureServiceWorker), and features.offline_pack false undoes it everywhere
// (AuthContext calls disableOffline once per load).
//
// ensureServiceWorker() resolving `null` means "unsupported here": no
// navigator.serviceWorker, not a secure context, the Vite dev server, or a
// registration the browser refused. Callers then keep the pack data only
// ("works while this tab stays open" when storageMode() is 'memory').
import { clearAllPacks } from './packStore'

const SW_URL = '/sw.js'
const READY_TIMEOUT_MS = 30_000
const PRECACHE_TIMEOUT_MS = 120_000

function supported() {
  if (import.meta.env.DEV) return false
  try {
    if (typeof window === 'undefined' || typeof navigator === 'undefined') return false
    if (!('serviceWorker' in navigator) || !navigator.serviceWorker) return false
    return window.isSecureContext !== false
  } catch { return false }
}

const timeout = (promise, ms) => Promise.race([
  promise,
  new Promise((_, reject) => setTimeout(() => reject(new Error('timeout')), ms)),
])

/** -> ServiceWorkerRegistration, or null when unsupported. */
export async function ensureServiceWorker() {
  if (!supported()) return null
  try {
    return (await navigator.serviceWorker.register(SW_URL, { scope: '/' })) || null
  } catch {
    return null
  }
}

function ask(worker, message, ms) {
  return timeout(new Promise((resolve) => {
    const channel = new MessageChannel()
    channel.port1.onmessage = (event) => { channel.port1.close(); resolve(event.data) }
    worker.postMessage(message, [channel.port2])
  }), ms)
}

/** Asks the worker to cache the app shell and assets -> {ok, kb}. */
export async function precacheShell() {
  if (!supported()) return { ok: false, kb: 0 }
  try {
    const reg = await navigator.serviceWorker.getRegistration('/')
    if (!reg) return { ok: false, kb: 0 }
    const worker = reg.active || (await timeout(navigator.serviceWorker.ready, READY_TIMEOUT_MS))?.active
    if (!worker) return { ok: false, kb: 0 }
    const reply = await ask(worker, { type: 'precache' }, PRECACHE_TIMEOUT_MS)
    return { ok: reply?.ok === true, kb: Math.round((Number(reply?.bytes) || 0) / 1024) }
  } catch {
    return { ok: false, kb: 0 }
  }
}

const isOurs = (reg) => [reg?.active, reg?.waiting, reg?.installing]
  .some((w) => typeof w?.scriptURL === 'string' && new URL(w.scriptURL, 'https://x.invalid').pathname === SW_URL)

/** Deletes every voyager-* cache, unregisters /sw.js and deletes every saved pack. */
export async function disableOffline() {
  try {
    if (typeof caches !== 'undefined' && caches?.keys) {
      const names = await caches.keys()
      await Promise.all(names.filter((n) => n.startsWith('voyager-')).map((n) => caches.delete(n)))
    }
  } catch { /* no Cache API */ }
  try {
    const sw = typeof navigator !== 'undefined' ? navigator.serviceWorker : null
    if (sw?.getRegistrations) {
      for (const reg of await sw.getRegistrations()) {
        if (!isOurs(reg)) continue
        try { reg.active?.postMessage({ type: 'purge' }) } catch { /* gone */ }
        await reg.unregister()
      }
    }
  } catch { /* unsupported */ }
  try { await clearAllPacks() } catch { /* no storage */ }
}
