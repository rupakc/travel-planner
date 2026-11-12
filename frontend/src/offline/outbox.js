// Per-user queue of writes made offline (expenses, journal entries, visited
// places, check-ins). Records live in IndexedDB keyed "<user_id>:<key>".
//
// An item's `path` is the API path relative to `/api`, exactly as
// services/tripsApi.js writes it (e.g. `/trips/12/journal`,
// `/trips/12/places/activity:x`). flush() prefixes `/api` and sends
// `Authorization: Bearer <token>` and the body as JSON.
//
// Exactly-once: every write the server accepts from here carries a
// `client_id` (the server answers a repeat with the existing row), and
// flush() is single-flight per user — concurrent calls in one tab share one
// run, and Web Locks (where available) serialise runs across tabs.
//
// Outcomes per item: 2xx and 409 → sent (removed); 408, 429 and 5xx → kept;
// 401 → kept and the run stops (the session ended: the same user's next
// sign-in sends them, a sign-out deletes them); any other 4xx → dropped
// (it would never succeed); a network error → kept and the run stops.
import { idbGet, idbPut, idbDelete, idbEntries, idbCount, idbDeletePrefix } from './idb'

const STORE = 'outbox'
/** Window event fired when the queue changes (OfflineBanner recounts). */
export const OUTBOX_CHANGED_EVENT = 'voyager:outbox-changed'
const AUTO_FLUSH_MS = 60_000

const userPrefix = (userId) => `${userId}:`
const none = () => ({ sent: 0, failed: 0, dropped: 0 })
let order = 0

function uuid() {
  try { if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID() } catch { /* fall through */ }
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`
}

function notify() {
  try { window.dispatchEvent(new Event(OUTBOX_CHANGED_EVENT)) } catch { /* no window */ }
}

function emitFlush(props) {
  import('../telemetry/client').then((m) => m.emit('outbox_flush', props)).catch(() => {})
}

/**
 * Queues one write. `path` is relative to /api. A repeated `key` replaces
 * the queued entry (keeping its place in the queue).
 */
export async function enqueue(userId, { method, path, body, key } = {}) {
  if (userId === null || userId === undefined) throw new Error('outbox needs a user id')
  if (!method || !path) throw new Error('outbox entries need a method and a path')
  const k = key ? String(key) : uuid()
  const id = `${userId}:${k}`
  const existing = await idbGet(STORE, id)
  const entry = {
    key: k,
    method: String(method).toUpperCase(),
    path: String(path),
    body: body === undefined ? null : body,
    queued_at: existing?.queued_at || new Date().toISOString(),
    order: existing?.order ?? Date.now() * 1000 + (order++ % 1000),
    rev: uuid(),
  }
  await idbPut(STORE, id, entry)
  notify()
  return entry
}

/** How many writes are waiting for this user. */
export async function pending(userId) {
  if (userId === null || userId === undefined) return 0
  return idbCount(STORE, userPrefix(userId))
}

/** Deletes this user's queue (sign-out, session_revoked). */
export async function clearOutbox(userId) {
  if (userId === null || userId === undefined) return
  await idbDeletePrefix(STORE, userPrefix(userId))
  notify()
}

// Removes an entry only if it is still the version that was sent: an entry
// replaced (same key) during the request is the newer write and stays.
async function removeIfUnchanged(id, rev) {
  const current = await idbGet(STORE, id)
  if (current && current.rev === rev) await idbDelete(STORE, id)
}

async function drain(token, userId, fetchImpl) {
  const items = (await idbEntries(STORE, userPrefix(userId))).sort(([, a], [, b]) => a.order - b.order)
  const out = none()
  for (let i = 0; i < items.length; i += 1) {
    const [id, item] = items[i]
    const headers = { Authorization: `Bearer ${token}` }
    const init = { method: item.method, headers }
    if (item.body !== null && item.body !== undefined) {
      headers['Content-Type'] = 'application/json'
      init.body = JSON.stringify(item.body)
    }
    let res
    try {
      res = await fetchImpl(`/api${item.path}`, init)
    } catch {
      out.failed += items.length - i
      break
    }
    const status = res?.status || 0
    if ((status >= 200 && status < 300) || status === 409) {
      await removeIfUnchanged(id, item.rev)
      out.sent += 1
    } else if (status === 401) {
      out.failed += items.length - i
      break
    } else if (status >= 400 && status < 500 && status !== 408 && status !== 429) {
      await removeIfUnchanged(id, item.rev)
      out.dropped += 1
    } else {
      out.failed += 1
    }
  }
  if (out.sent || out.failed || out.dropped) {
    emitFlush(out)
    notify()
  }
  return out
}

function withLock(name, fn) {
  try {
    if (typeof navigator !== 'undefined' && navigator.locks?.request) return navigator.locks.request(name, fn)
  } catch { /* no Web Locks */ }
  return fn()
}

const inflight = new Map()

/**
 * Sends this user's queued writes in order -> {sent, failed, dropped}.
 * Single-flight: a call while a run is going returns that run.
 */
export function flush(token, userId, fetchImpl) {
  if (!token || userId === null || userId === undefined) return Promise.resolve(none())
  const k = String(userId)
  if (inflight.has(k)) return inflight.get(k)
  const send = fetchImpl || ((...args) => fetch(...args))
  const runPromise = Promise.resolve()
    .then(() => withLock(`voyager-outbox:${k}`, () => drain(token, userId, send)))
    .finally(() => { inflight.delete(k) })
  inflight.set(k, runPromise)
  return runPromise
}

/**
 * Flushes on `online` and every 60 s while items are queued (also once at
 * start, for writes queued before a reload). Returns stop().
 */
export function startAutoFlush(getToken, getUserId) {
  if (typeof window === 'undefined') return () => {}
  let stopped = false
  const tick = async () => {
    if (stopped) return
    const token = getToken?.()
    const userId = getUserId?.()
    if (!token || userId === null || userId === undefined) return
    try {
      if (typeof navigator !== 'undefined' && navigator.onLine === false) return
      if ((await pending(userId)) === 0 || stopped) return
      await flush(token, userId)
    } catch { /* next tick */ }
  }
  const onOnline = () => { tick() }
  window.addEventListener('online', onOnline)
  const timer = setInterval(tick, AUTO_FLUSH_MS)
  tick()
  return () => {
    stopped = true
    window.removeEventListener('online', onOnline)
    clearInterval(timer)
  }
}
