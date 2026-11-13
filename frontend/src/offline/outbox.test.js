import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

const emitted = vi.hoisted(() => [])
vi.mock('../telemetry/client', () => ({ emit: (event, props) => { emitted.push([event, props]) } }))

import { enqueue, flush, pending, clearOutbox, startAutoFlush, listRejected, dismissRejected } from './outbox'
import { _resetForTests } from './idb'

const ok = (status = 201) => ({ ok: status >= 200 && status < 300, status, json: async () => ({}) })

beforeEach(() => { _resetForTests(); emitted.length = 0 })
afterEach(() => { vi.useRealTimers() })

describe('outbox', () => {
  it('a 409 per-trip cap is rejected (kept, listed, not retried); other 409 is sent', async () => {
    await enqueue(7, { method: 'POST', path: '/trips/1/expenses', body: { client_id: 'a' }, key: 'exp:a' })
    await enqueue(7, { method: 'POST', path: '/trips/1/journal', body: { client_id: 'b' }, key: 'j:b' })
    const fetchImpl = vi.fn(async (url) => (url.endsWith('expenses')
      ? { status: 409, json: async () => ({ code: 'expense_limit' }) }
      : { status: 409, json: async () => ({ code: 'conflict' }) }))
    expect(await flush('tok', 7, fetchImpl)).toEqual({ sent: 1, failed: 0, dropped: 0, rejected: 1 })
    expect(await pending(7)).toBe(0)
    const rej = await listRejected(7, '/trips/1/expenses')
    expect(rej).toHaveLength(1)
    expect(rej[0].rejected).toBe('expense_limit')
    expect(rej[0].body.client_id).toBe('a')
    expect(await listRejected(7, '/trips/1/journal')).toHaveLength(0)
    const again = vi.fn()
    expect(await flush('tok', 7, again)).toEqual({ sent: 0, failed: 0, dropped: 0, rejected: 0 })
    expect(again).not.toHaveBeenCalled()
    await dismissRejected(7, 'exp:a')
    expect(await listRejected(7)).toHaveLength(0)
  })

  it('queues per user, and a repeated key replaces the entry', async () => {
    await enqueue(7, { method: 'POST', path: '/trips/12/expenses', body: { client_id: 'a', amount: '1.00' }, key: 'exp:a' })
    await enqueue(7, { method: 'POST', path: '/trips/12/expenses', body: { client_id: 'a', amount: '2.00' }, key: 'exp:a' })
    await enqueue(7, { method: 'PUT', path: '/trips/12/places/activity:x', body: { visited: true } })
    await enqueue(8, { method: 'POST', path: '/trips/3/journal', body: {}, key: 'j:1' })
    expect(await pending(7)).toBe(2)
    expect(await pending(8)).toBe(1)
    const fetchImpl = vi.fn().mockResolvedValue(ok())
    expect(await flush('tok', 7, fetchImpl)).toEqual({ sent: 2, failed: 0, dropped: 0, rejected: 0 })
    expect(fetchImpl).toHaveBeenCalledTimes(2)
    const [url, init] = fetchImpl.mock.calls[0]
    expect(url).toBe('/api/trips/12/expenses')
    expect(init.method).toBe('POST')
    expect(init.headers.Authorization).toBe('Bearer tok')
    expect(JSON.parse(init.body).amount).toBe('2.00')
    expect(await pending(7)).toBe(0)
    expect(await pending(8)).toBe(1)
    await vi.waitFor(() => expect(emitted).toEqual([['outbox_flush', { sent: 2, failed: 0, dropped: 0, rejected: 0 }]]))
  })

  it('concurrent flushes send each item once', async () => {
    for (let i = 0; i < 3; i += 1) {
      await enqueue(7, { method: 'POST', path: `/trips/12/expenses`, body: { client_id: `c${i}` }, key: `exp:c${i}` })
    }
    const fetchImpl = vi.fn(() => new Promise((resolve) => setTimeout(() => resolve(ok()), 5)))
    const [a, b, c] = await Promise.all([flush('tok', 7, fetchImpl), flush('tok', 7, fetchImpl), flush('tok', 7, fetchImpl)])
    expect(fetchImpl).toHaveBeenCalledTimes(3)
    const ids = fetchImpl.mock.calls.map(([, init]) => JSON.parse(init.body).client_id).sort()
    expect(ids).toEqual(['c0', 'c1', 'c2'])
    expect(a).toEqual({ sent: 3, failed: 0, dropped: 0, rejected: 0 })
    expect(b).toEqual(a)
    expect(c).toEqual(a)
    // a later flush finds nothing left
    expect(await flush('tok', 7, fetchImpl)).toEqual({ sent: 0, failed: 0, dropped: 0, rejected: 0 })
    expect(fetchImpl).toHaveBeenCalledTimes(3)
  })

  it('a 5xx is kept, a 400 is dropped, a 409 counts as sent, 408/429 are kept', async () => {
    const statuses = { k500: 503, k400: 400, k409: 409, k408: 408, k429: 429, k422: 422 }
    for (const key of Object.keys(statuses)) {
      await enqueue(7, { method: 'POST', path: '/trips/1/expenses', body: { key }, key })
    }
    const fetchImpl = vi.fn(async (url, init) => ok(statuses[JSON.parse(init.body).key]))
    expect(await flush('tok', 7, fetchImpl)).toEqual({ sent: 1, failed: 3, dropped: 2, rejected: 0 })
    expect(await pending(7)).toBe(3)
    const again = vi.fn(async () => ok(200))
    expect(await flush('tok', 7, again)).toEqual({ sent: 3, failed: 0, dropped: 0, rejected: 0 })
    const keys = again.mock.calls.map(([, init]) => JSON.parse(init.body).key).sort()
    expect(keys).toEqual(['k408', 'k429', 'k500'])
  })

  it('a network error keeps everything and stops the run', async () => {
    await enqueue(7, { method: 'POST', path: '/trips/1/expenses', body: {}, key: 'a' })
    await enqueue(7, { method: 'POST', path: '/trips/1/expenses', body: {}, key: 'b' })
    const fetchImpl = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'))
    expect(await flush('tok', 7, fetchImpl)).toEqual({ sent: 0, failed: 2, dropped: 0, rejected: 0 })
    expect(fetchImpl).toHaveBeenCalledTimes(1)
    expect(await pending(7)).toBe(2)
  })

  it('a 401 keeps the queue for the next sign-in', async () => {
    await enqueue(7, { method: 'POST', path: '/trips/1/expenses', body: {}, key: 'a' })
    await enqueue(7, { method: 'POST', path: '/trips/1/expenses', body: {}, key: 'b' })
    const fetchImpl = vi.fn(async () => ({ ok: false, status: 401, json: async () => ({ detail: 'x' }) }))
    expect(await flush('tok', 7, fetchImpl)).toEqual({ sent: 0, failed: 2, dropped: 0, rejected: 0 })
    expect(await pending(7)).toBe(2)
  })

  it('an entry replaced while it was being sent is kept (the newer version goes next time)', async () => {
    await enqueue(7, { method: 'PUT', path: '/trips/1/places/a', body: { v: 1 }, key: 'p' })
    const fetchImpl = vi.fn(async () => {
      await enqueue(7, { method: 'PUT', path: '/trips/1/places/a', body: { v: 2 }, key: 'p' })
      return ok(200)
    })
    await flush('tok', 7, fetchImpl)
    expect(await pending(7)).toBe(1)
    const next = vi.fn(async () => ok(200))
    await flush('tok', 7, next)
    expect(JSON.parse(next.mock.calls[0][1].body).v).toBe(2)
  })

  it('clearOutbox clears only that user', async () => {
    await enqueue(1, { method: 'POST', path: '/x', body: {}, key: 'a' })
    await enqueue(2, { method: 'POST', path: '/x', body: {}, key: 'a' })
    await clearOutbox(1)
    expect(await pending(1)).toBe(0)
    expect(await pending(2)).toBe(1)
  })

  it('startAutoFlush sends on `online` and every 60 s while items are queued', async () => {
    vi.useFakeTimers()
    const calls = []
    vi.stubGlobal('fetch', vi.fn(async (url) => { calls.push(url); return ok(200) }))
    const stop = startAutoFlush(() => 'tok', () => 7)
    await vi.advanceTimersByTimeAsync(60_000)
    expect(calls).toEqual([]) // nothing queued yet
    await enqueue(7, { method: 'POST', path: '/trips/1/journal', body: {}, key: 'j' })
    window.dispatchEvent(new Event('online'))
    await vi.advanceTimersByTimeAsync(10)
    expect(calls).toEqual(['/api/trips/1/journal'])
    await enqueue(7, { method: 'POST', path: '/trips/1/journal', body: {}, key: 'k' })
    await vi.advanceTimersByTimeAsync(60_000)
    expect(calls).toHaveLength(2)
    stop()
    await enqueue(7, { method: 'POST', path: '/trips/1/journal', body: {}, key: 'l' })
    window.dispatchEvent(new Event('online'))
    await vi.advanceTimersByTimeAsync(120_000)
    expect(calls).toHaveLength(2)
    vi.unstubAllGlobals()
  })
})
