// Web performance and error capture. Metrics: TTFB and FCP from navigation and
// paint timing; LCP, INP (max `event` entry duration), CLS and the long-task
// count from PerformanceObserver where supported, reported when the page is
// hidden. Errors report their kind and `file:line` only, never the message.

import { currentRoute } from './routes'

const ID_RE = /^[A-Za-z0-9_.:/-]{1,64}$/
const MAX_ERRORS = 20 // per page load: an error loop must not become a storm

const round = (v) => Math.round(v * 1000) / 1000

function supported(type) {
  try {
    return typeof PerformanceObserver !== 'undefined'
      && (PerformanceObserver.supportedEntryTypes || []).includes(type)
  } catch {
    return false
  }
}

function observe(type, onEntries, extra = {}) {
  if (!supported(type)) return null
  try {
    const po = new PerformanceObserver((list) => {
      try { onEntries(list.getEntries()) } catch { /* ignore */ }
    })
    po.observe({ type, buffered: true, ...extra })
    return po
  } catch {
    return null
  }
}

function basename(file) {
  if (typeof file !== 'string' || !file) return ''
  const clean = file.split(/[?#]/)[0]
  return clean.slice(clean.lastIndexOf('/') + 1)
}

export function errorSource(file, line) {
  const name = basename(file).replace(/[^A-Za-z0-9_.-]/g, '_').slice(0, 54)
  if (!name) return 'unknown'
  const value = Number.isFinite(line) && line > 0 ? `${name}:${line}` : name
  return ID_RE.test(value) ? value : 'unknown'
}

// First "file.js:line" frame in a stack trace.
function stackSource(stack) {
  if (typeof stack !== 'string') return 'unknown'
  const m = stack.match(/([^\s/()@]+\.(?:m?js|jsx|ts|tsx)(?:\?[^:\s)]*)?):(\d+)/)
  return m ? errorSource(m[1], Number(m[2])) : 'unknown'
}

export function startPerf(emit) {
  const observers = []
  const vitals = {
    lcp: null,
    inp: null,
    cls: supported('layout-shift') ? 0 : null,
    long_task: supported('longtask') ? 0 : null,
  }
  const reported = {}
  const send = (metric, value) => {
    if (!Number.isFinite(value)) return
    emit('perf', { metric, value: round(value), route: currentRoute() })
  }

  try {
    const nav = performance.getEntriesByType?.('navigation')?.[0]
    if (nav && nav.responseStart > 0) send('ttfb', nav.responseStart)
  } catch { /* ignore */ }

  const fcpObs = observe('paint', (entries) => {
    for (const e of entries) {
      if (e.name === 'first-contentful-paint' && !reported.fcp) {
        reported.fcp = true
        send('fcp', e.startTime)
      }
    }
  })
  if (fcpObs) observers.push(fcpObs)

  const add = (po) => { if (po) observers.push(po) }
  add(observe('largest-contentful-paint', (entries) => {
    const last = entries.at(-1)
    if (last) vitals.lcp = last.renderTime || last.startTime
  }))
  add(observe('event', (entries) => {
    for (const e of entries) vitals.inp = Math.max(vitals.inp ?? 0, e.duration)
  }, { durationThreshold: 40 }))
  add(observe('layout-shift', (entries) => {
    for (const e of entries) if (!e.hadRecentInput) vitals.cls += e.value
  }))
  add(observe('longtask', (entries) => { vitals.long_task += entries.length }))

  // Called on every page hide; each metric is sent again only if it changed.
  const reportVitals = () => {
    try {
      for (const metric of ['lcp', 'inp', 'cls', 'long_task']) {
        const v = vitals[metric]
        if (v === null || reported[metric] === v) continue
        reported[metric] = v
        send(metric, v)
      }
    } catch { /* ignore */ }
  }

  let errors = 0
  const onError = (event) => {
    try {
      if (errors >= MAX_ERRORS) return
      errors += 1
      const source = event.filename
        ? errorSource(event.filename, event.lineno)
        : stackSource(event.error?.stack)
      emit('error', { kind: 'js', source })
    } catch { /* ignore */ }
  }
  const onRejection = (event) => {
    try {
      if (errors >= MAX_ERRORS) return
      errors += 1
      emit('error', { kind: 'promise', source: stackSource(event.reason?.stack) })
    } catch { /* ignore */ }
  }
  window.addEventListener('error', onError)
  window.addEventListener('unhandledrejection', onRejection)

  return {
    reportVitals,
    stop() {
      for (const po of observers) { try { po.disconnect() } catch { /* ignore */ } }
      window.removeEventListener('error', onError)
      window.removeEventListener('unhandledrejection', onRejection)
    },
  }
}
