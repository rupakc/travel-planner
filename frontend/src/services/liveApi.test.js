// @vitest-environment node
import { describe, it, expect, vi, beforeEach } from 'vitest'

const http = vi.hoisted(() => ({
  get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn(), put: vi.fn(),
  interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
}))
vi.mock('axios', () => ({ default: { create: () => http } }))

import { fetchNearby, liveCheckWatch } from './api'

const auth = { headers: { Authorization: 'Bearer tok' } }

beforeEach(() => { http.post.mockReset().mockResolvedValue({ data: { ok: 1 } }) })

describe('live API helpers', () => {
  it('asks /nearby for the v2 sections', async () => {
    expect(await fetchNearby({ lat: 38.72, lng: -9.14 }, 'tok')).toEqual({ ok: 1 })
    expect(http.post).toHaveBeenLastCalledWith('/nearby', { lat: 38.72, lng: -9.14, sections: true }, auth)
  })

  it('sends only kind + watch_id to /live-check', async () => {
    expect(await liveCheckWatch('hotel', 12, 'tok')).toEqual({ ok: 1 })
    expect(http.post).toHaveBeenLastCalledWith('/live-check', { kind: 'hotel', watch_id: 12 }, auth)
    await liveCheckWatch('flight', 3, 'tok')
    expect(http.post).toHaveBeenLastCalledWith('/live-check', { kind: 'flight', watch_id: 3 }, auth)
  })
})
