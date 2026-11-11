/**
 * Lightweight analytics client.
 * Batches events and flushes every 5s or when the batch hits 10.
 * Token is resolved lazily from localStorage so the module is importable anywhere.
 * Covered by the same switch as product telemetry: nothing is queued or sent
 * unless telemetryAllowed() (EU consent, Preferences, "Privacy choices").
 */

import { telemetryAllowed } from '../telemetry/consent'

let _batch = []
let _timer = null
const FLUSH_INTERVAL = 5000
const FLUSH_SIZE = 10

function _token() {
  return localStorage.getItem('tp_token')
}

function _flush() {
  if (!_batch.length) return
  const events = _batch.splice(0, _batch.length)
  if (!telemetryAllowed()) return // opted out since these were queued: drop
  const token = _token()
  if (!token) return
  fetch('/api/analytics/events', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({ events }),
  }).catch(() => {}) // analytics are non-critical; silently swallow errors
}

function _schedule() {
  if (_timer) return
  _timer = setTimeout(() => { _timer = null; _flush() }, FLUSH_INTERVAL)
}

// Mirrored into product telemetry as feature_used (feature + page only, never
// the metadata). Called through import() and never awaited, so it can't slow
// the caller, and a failing SDK is ignored (the SDK is in the main bundle).
function _mirror(feature, page) {
  try {
    import('../telemetry/client')
      .then((m) => m.emit('feature_used', { feature, page }))
      .catch(() => {})
  } catch { /* telemetry must never break tracking */ }
}

export function track(feature, page, metadata = {}) {
  if (!telemetryAllowed()) return
  _mirror(feature, page)
  _batch.push({ feature, page, metadata, ts: Date.now() })
  if (_batch.length >= FLUSH_SIZE) {
    clearTimeout(_timer)
    _timer = null
    _flush()
  } else {
    _schedule()
  }
}

// Flush on page unload so we don't lose the last batch
if (typeof window !== 'undefined') {
  window.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') _flush()
  })
}
