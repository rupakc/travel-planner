// Background product telemetry for the web app.
//
// Events queue in memory and go to POST /api/telemetry in batches (every
// `flush_interval_s`, or at `max_batch`). When the page is hidden the rest is
// sent with fetch(keepalive) + auth when signed in, else navigator.sendBeacon
// (which can't carry auth headers). Nothing here may block, slow or break the
// UI: every entry point swallows its own errors, nothing on a user path is
// awaited, and an old backend (404) or a disabled server turns it off for the
// session with no retries. The server derives user_id from the bearer token;
// no user id is ever stored here.

import { telemetryAllowed } from './consent'
import { routeTemplate, currentRoute } from './routes'
import { startAutocapture } from './autocapture'
import { startPerf } from './perf'

const ENDPOINT = '/api/telemetry'
const CONFIG_URL = '/api/config'
const QUEUE_KEY = 'tp_tq'
const ANON_KEY = 'tp_anon'
const SESSION_KEY = 'tp_tsess' // sessionStorage: the session survives reloads in a tab
const TOKEN_KEY = 'tp_token'
const QUEUE_CAP = 500
const SESSION_IDLE_MS = 30 * 60 * 1000
const FAILS_BEFORE_BACKOFF = 3
const MAX_BACKOFF_MS = 5 * 60 * 1000
const MAX_EVENT_AGE_MS = 7 * 24 * 60 * 60 * 1000 // the server's clock-skew window
const SERVER_MAX_BATCH = 100

const ID_RE = /^[A-Za-z0-9_.:/-]{1,64}$/
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

// ── module state ────────────────────────────────────────────────────────────
let state = 'pending' // 'pending' (before /api/config) | 'on' | 'off'
let queue = []
let inflight = new Set() // events in a regular POST right now
let cfg = { interval: 15000, maxBatch: 50 }
let appVersion = '0.0.0'
let ready = null
let timer = null
let timerDue = 0
let sending = false
let failures = 0
let blockedUntil = 0
let userPresent = null
let anonMemory = null
let session = null
let screen = null // { route, since }
let collectors = null // { stopCapture, perf }
let listening = false
let hiddenHandled = false

// ── small safe helpers ──────────────────────────────────────────────────────
const store = (kind) => {
  try { return kind === 'session' ? window.sessionStorage : window.localStorage } catch { return null }
}
function sGet(key, kind) {
  try { return store(kind)?.getItem(key) ?? null } catch { return null }
}
function sSet(key, value, kind) {
  try { store(kind)?.setItem(key, value) } catch { /* storage blocked or full */ }
}
function sRemove(key, kind) {
  try { store(kind)?.removeItem(key) } catch { /* storage blocked */ }
}

function idle(fn) {
  const run = () => { try { fn() } catch { /* ignore */ } }
  try {
    if (typeof window.requestIdleCallback === 'function') return void window.requestIdleCallback(run, { timeout: 2000 })
  } catch { /* fall through */ }
  setTimeout(run, 1)
}

export function uuid() {
  try {
    const v = globalThis.crypto?.randomUUID?.()
    if (typeof v === 'string' && UUID_RE.test(v)) return v.toLowerCase()
  } catch { /* insecure context or missing API */ }
  const b = new Uint8Array(16)
  try {
    globalThis.crypto.getRandomValues(b)
  } catch {
    for (let i = 0; i < 16; i++) b[i] = Math.floor(Math.random() * 256)
  }
  b[6] = (b[6] & 0x0f) | 0x40
  b[8] = (b[8] & 0x3f) | 0x80
  const h = Array.from(b, (x) => x.toString(16).padStart(2, '0')).join('')
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`
}

function anonId() {
  if (anonMemory) return anonMemory
  const saved = sGet(ANON_KEY)
  if (saved && UUID_RE.test(saved)) {
    anonMemory = saved
  } else {
    anonMemory = uuid()
    sSet(ANON_KEY, anonMemory)
  }
  return anonMemory
}

// Returns the current session, starting a new one after 30 min idle.
function touchSession(now) {
  if (!session) {
    try {
      const saved = JSON.parse(sGet(SESSION_KEY, 'session') || 'null')
      if (saved && UUID_RE.test(saved.id) && Number.isFinite(saved.last)) session = saved
    } catch { /* ignore */ }
  }
  let isNew = false
  if (!session || now - session.last > SESSION_IDLE_MS || now < session.last - SESSION_IDLE_MS) {
    session = { id: uuid(), last: now }
    isNew = true
  }
  const wrote = session.lastWritten || 0
  session.last = now
  if (isNew || now - wrote > 10_000) {
    session.lastWritten = now
    sSet(SESSION_KEY, JSON.stringify({ id: session.id, last: now }), 'session')
  }
  return { id: session.id, isNew }
}

function cleanVersion(v) {
  const s = String(v ?? '').replace(/[^A-Za-z0-9_.:/-]/g, '_').slice(0, 64)
  return s || '0.0.0'
}

function locale() {
  try {
    const l = document.documentElement.lang || navigator.language || 'en'
    return ID_RE.test(l) && l.length <= 16 ? l : 'en'
  } catch {
    return 'en'
  }
}

// Only short token-like strings, finite numbers and booleans are kept: free
// text never leaves the browser even if a caller passes it by mistake.
function cleanProps(props) {
  const out = {}
  if (!props || typeof props !== 'object') return out
  for (const key of Object.keys(props)) {
    const v = props[key]
    if (typeof v === 'boolean' || (typeof v === 'number' && Number.isFinite(v))) out[key] = v
    else if (typeof v === 'string' && ID_RE.test(v)) out[key] = v
  }
  return out
}

function clamp(v, lo, hi, fallback) {
  const n = Number(v)
  return Number.isFinite(n) ? Math.min(hi, Math.max(lo, Math.round(n))) : fallback
}

// ── queue ───────────────────────────────────────────────────────────────────
function push(entry) {
  queue.push(entry)
  if (queue.length > QUEUE_CAP) queue.splice(0, queue.length - QUEUE_CAP)
}

function enqueue(event, props) {
  const now = Date.now()
  const s = touchSession(now)
  const route = currentRoute()
  if (s.isNew) push({ event: 'session_start', ts: now, props: {}, screen: route, sid: s.id })
  push({ event, ts: now, props: cleanProps(props), screen: route, sid: s.id })
  scheduleFlush()
}

function clearQueue() {
  queue = []
  inflight = new Set()
  sRemove(QUEUE_KEY)
}

// The queue is written to storage only when the page is hidden or a send
// fails, and claimed (read + removed) at start-up, so two tabs don't keep
// resending each other's events.
function persist() {
  if (state !== 'on') return
  if (!queue.length) return sRemove(QUEUE_KEY)
  try { sSet(QUEUE_KEY, JSON.stringify(queue)) } catch { /* ignore */ }
}

function restoreQueue() {
  let saved
  try { saved = JSON.parse(sGet(QUEUE_KEY) || '[]') } catch { saved = [] }
  sRemove(QUEUE_KEY)
  if (!Array.isArray(saved)) return
  const now = Date.now()
  const valid = saved.filter((e) => e && typeof e.event === 'string'
    && Number.isFinite(e.ts) && Math.abs(now - e.ts) < MAX_EVENT_AGE_MS)
    .map((e) => ({
      event: e.event,
      ts: e.ts,
      props: cleanProps(e.props),
      screen: typeof e.screen === 'string' && ID_RE.test(e.screen) ? e.screen : '/',
      sid: typeof e.sid === 'string' && UUID_RE.test(e.sid) ? e.sid : null,
    }))
  queue = valid.concat(queue)
  if (queue.length > QUEUE_CAP) queue.splice(0, queue.length - QUEUE_CAP)
}

// Next batch: up to max_batch events of one session (the client block names
// one session), skipping events already in flight.
function takeBatch(exclude) {
  const batch = []
  let sid
  for (const e of queue) {
    if (exclude.has(e)) continue
    const id = e.sid || (session && session.id) || null
    if (batch.length === 0) sid = id
    else if (id !== sid) continue
    batch.push(e)
    if (batch.length >= cfg.maxBatch) break
  }
  return { batch, sid }
}

function payload(batch, sid) {
  return JSON.stringify({
    client: {
      anon_id: anonId(),
      session_id: sid && UUID_RE.test(sid) ? sid : touchSession(Date.now()).id,
      platform: 'web',
      app_version: appVersion,
      locale: locale(),
    },
    events: batch.map(({ event, ts, props, screen: s }) => ({ event, ts, props, screen: s })),
  })
}

function removeSent(batch) {
  const sent = new Set(batch)
  queue = queue.filter((e) => !sent.has(e))
}

function authHeaders() {
  const headers = { 'Content-Type': 'application/json' }
  if (userPresent === false) return headers
  const token = sGet(TOKEN_KEY)
  if (token) headers.Authorization = `Bearer ${token}`
  return headers
}

// ── sending ─────────────────────────────────────────────────────────────────
function schedule(delay) {
  const due = Date.now() + delay
  if (timer && timerDue <= due) return
  clearTimeout(timer)
  timerDue = due
  timer = setTimeout(() => {
    timer = null
    idle(flush) // the JSON + network work runs in idle time
  }, delay)
}

function scheduleFlush() {
  if (state !== 'on' || !queue.length) return
  const wait = Math.max(0, blockedUntil - Date.now())
  schedule(queue.length >= cfg.maxBatch ? wait : Math.max(wait, cfg.interval))
}

function onFailure() {
  failures += 1
  if (failures >= FAILS_BEFORE_BACKOFF) {
    const delay = Math.min(MAX_BACKOFF_MS, cfg.interval * 2 ** (failures - FAILS_BEFORE_BACKOFF + 1))
    blockedUntil = Date.now() + delay
  }
  persist()
}

function onSuccess() {
  failures = 0
  blockedUntil = 0
}

// Handles one response. Returns true when the batch is done with (sent, or
// rejected for good), false to keep it for a retry.
function handleResponse(r, batch) {
  if (r.status === 404) {
    disable()
    return false
  }
  // 2xx sent; other 4xx (413/422/...) would fail forever, so drop the batch.
  if (r.ok || (r.status >= 400 && r.status < 500 && r.status !== 408 && r.status !== 429)) {
    removeSent(batch)
    onSuccess()
    return true
  }
  onFailure()
  return false
}

async function sendOne() {
  const { batch, sid } = takeBatch(new Set())
  if (!batch.length) return false
  for (const e of batch) inflight.add(e)
  let r
  try {
    r = await fetch(ENDPOINT, {
      method: 'POST',
      headers: authHeaders(),
      body: payload(batch, sid),
      credentials: 'same-origin',
    })
  } catch {
    if (state === 'on') onFailure()
    return false
  } finally {
    for (const e of batch) inflight.delete(e)
  }
  if (state !== 'on') return false
  return handleResponse(r, batch)
}

async function drain() {
  if (sending) return
  sending = true
  try {
    while (state === 'on' && queue.length && Date.now() >= blockedUntil) {
      if (!(await sendOne())) break
    }
  } finally {
    sending = false
    scheduleFlush()
  }
}

// Sends what's queued now (the regular timer calls this too). Never rejects.
export function flush() {
  try {
    return Promise.resolve(ready).then(() => drain()).catch(() => {})
  } catch {
    return Promise.resolve()
  }
}

function beacon(body) {
  try {
    if (typeof navigator.sendBeacon !== 'function') return false
    return navigator.sendBeacon(ENDPOINT, new Blob([body], { type: 'application/json' }))
  } catch {
    return false
  }
}

// Page hidden: send everything left. Signed in → fetch(keepalive) with auth,
// falling back to an (anonymous) beacon; anonymous → beacon straight away.
function flushOnHide() {
  if (state !== 'on' || Date.now() < blockedUntil) return
  const taken = new Set(inflight)
  for (;;) {
    const { batch, sid } = takeBatch(taken)
    if (!batch.length) break
    for (const e of batch) taken.add(e)
    const body = payload(batch, sid)
    const headers = authHeaders()
    const viaBeacon = () => {
      if (beacon(body)) removeSent(batch)
    }
    if (headers.Authorization || typeof navigator.sendBeacon !== 'function') {
      try {
        fetch(ENDPOINT, { method: 'POST', headers, body, keepalive: true, credentials: 'same-origin' })
          .then((r) => { if (state === 'on') handleResponse(r, batch) })
          .catch(() => viaBeacon())
      } catch {
        viaBeacon()
      }
    } else {
      viaBeacon()
    }
  }
}

// ── lifecycle ───────────────────────────────────────────────────────────────
function emitScreenTime(now) {
  if (!screen) return
  const ms = Math.max(0, Math.round(now - screen.since))
  emit('screen_time', { route: screen.route, ms })
}

function onHidden() {
  if (hiddenHandled) return
  hiddenHandled = true
  const now = Date.now()
  emitScreenTime(now)
  collectors?.perf?.reportVitals()
  emit('app_background')
  flushOnHide()
  persist()
}

function onVisibility() {
  try {
    if (document.visibilityState === 'hidden') {
      onHidden()
    } else if (hiddenHandled) {
      hiddenHandled = false
      if (screen) screen.since = Date.now()
      sRemove(QUEUE_KEY) // still held in memory
    }
  } catch { /* ignore */ }
}

function onPageHide() {
  try { onHidden() } catch { /* ignore */ }
}

function startListening() {
  if (listening) return
  listening = true
  document.addEventListener('visibilitychange', onVisibility)
  window.addEventListener('pagehide', onPageHide)
}

function stopListening() {
  if (!listening) return
  listening = false
  document.removeEventListener('visibilitychange', onVisibility)
  window.removeEventListener('pagehide', onPageHide)
}

function startCollectors() {
  if (collectors || state !== 'on') return
  collectors = {}
  try { collectors.stopCapture = startAutocapture(emit) } catch { /* ignore */ }
  try { collectors.perf = startPerf(emit) } catch { /* ignore */ }
}

function stopCollectors() {
  if (!collectors) return
  try { collectors.stopCapture?.() } catch { /* ignore */ }
  try { collectors.perf?.stop() } catch { /* ignore */ }
  collectors = null
}

function disable() {
  state = 'off'
  clearTimeout(timer)
  timer = null
  stopCollectors()
  stopListening()
  clearQueue()
}

function apply(conf) {
  const t = conf && conf.telemetry
  if (!t || t.enabled !== true) return disable()
  cfg = {
    interval: clamp(t.flush_interval_s, 1, 300, 15) * 1000,
    maxBatch: clamp(t.max_batch, 1, SERVER_MAX_BATCH, 50),
  }
  state = 'on'
  startListening()
  if (!telemetryAllowed()) {
    // Not consented: only a recorded consent choice (and its session) may go.
    const keep = queue.filter((e) => e.event === 'consent' || e.event === 'session_start')
    clearQueue()
    queue = keep.some((e) => e.event === 'consent') ? keep : []
    scheduleFlush()
    return
  }
  restoreQueue()
  emit('app_open')
  startCollectors()
  scheduleFlush()
}

async function loadConfig() {
  const r = await fetch(CONFIG_URL, { credentials: 'same-origin' })
  return r.ok ? r.json() : null
}

// ── public API ──────────────────────────────────────────────────────────────

/** Fetches /api/config once; 404, an error or `enabled:false` → off for the session. */
export function initTelemetry({ appVersion: version } = {}) {
  try {
    if (ready) return
    appVersion = cleanVersion(version)
    ready = loadConfig().then(apply).catch(() => disable())
  } catch {
    disable()
  }
}

/** Queues one event. Never throws; a no-op when telemetry is off or not consented. */
export function emit(event, props) {
  try {
    if (state === 'off' || typeof event !== 'string' || !ID_RE.test(event)) return
    if (event === 'consent') {
      // The choice itself is always recorded; a denial drops everything else.
      const choice = props && props.choice
      if (choice === 'denied') {
        clearQueue()
        stopCollectors()
      }
      enqueue(event, props)
      if (choice === 'granted') startCollectors()
      return
    }
    if (!telemetryAllowed()) return
    enqueue(event, props)
  } catch { /* never break the caller */ }
}

/** Screen view for a pathname (route template only), with screen_time for the previous one. */
export function screenView(pathname) {
  try {
    const route = routeTemplate(pathname)
    if (screen && screen.route === route) return
    const now = Date.now()
    const referrer = screen && screen.route
    emitScreenTime(now)
    screen = { route, since: now }
    emit('screen_view', referrer ? { route, referrer_route: referrer } : { route })
  } catch { /* ignore */ }
}

/** Whether a signed-in user is present: false never attaches the bearer token. */
export function setUserPresent(present) {
  try { userPresent = !!present } catch { /* ignore */ }
}

// ── test hooks ──────────────────────────────────────────────────────────────
export function _queueForTests() {
  return queue.slice()
}

export function _resetForTests() {
  disable()
  state = 'pending'
  ready = null
  failures = 0
  blockedUntil = 0
  sending = false
  userPresent = null
  anonMemory = null
  session = null
  screen = null
  hiddenHandled = false
}
