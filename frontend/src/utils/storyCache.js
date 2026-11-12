import { getStory } from '../services/alertsApi'

// Shared story loader for the Alerts page: one request per kind:id:last_checked_at
// (a newer check is a new key), at most LIMIT in flight at once.
const LIMIT = 3
const cache = new Map()
const queue = []
let active = 0

function pump() {
  while (active < LIMIT && queue.length) {
    const job = queue.shift()
    active += 1
    getStory(job.token, job.kind, job.id).then(job.resolve, job.reject).finally(() => { active -= 1; pump() })
  }
}

export function loadStory(token, kind, id, stamp = '') {
  const key = `${kind}:${id}:${stamp || ''}`
  if (!cache.has(key)) {
    const p = new Promise((resolve, reject) => { queue.push({ token, kind, id, resolve, reject }) })
    p.catch(() => { if (cache.get(key) === p) cache.delete(key) })  // retry after a failure
    cache.set(key, p)
    pump()
  }
  return cache.get(key)
}

export function _resetStoryCache() { cache.clear(); queue.length = 0; active = 0 }
