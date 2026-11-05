// @vitest-environment node
import { describe, it, expect, vi, beforeEach } from 'vitest'

const http = vi.hoisted(() => ({
  get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn(), put: vi.fn(),
  interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
}))
vi.mock('axios', () => ({ default: { create: () => http } }))

import {
  checkPriceWatchNow, createPriceWatch, deletePriceWatch, listPriceWatches, matchPriceWatch,
  updatePriceWatch,
} from './api'

const auth = { headers: { Authorization: 'Bearer tok' } }

beforeEach(() => {
  for (const fn of ['get', 'post', 'patch', 'delete']) http[fn].mockReset().mockResolvedValue({ data: { ok: 1 } })
})

describe('price watch API', () => {
  it('lists all or one kind', async () => {
    await listPriceWatches('tok')
    expect(http.get).toHaveBeenLastCalledWith('/price-watches', { ...auth, params: undefined })
    await listPriceWatches('tok', 'hotel')
    expect(http.get).toHaveBeenLastCalledWith('/price-watches', { ...auth, params: { kind: 'hotel' } })
  })

  it('matches, creates, updates, deletes and checks', async () => {
    http.post.mockResolvedValueOnce({ data: { watch: { id: 3 } } })
    const body = { kind: 'hotel', hotel: { name: 'Lumen' } }
    expect(await matchPriceWatch(body, 'tok')).toEqual({ id: 3 })
    expect(http.post).toHaveBeenLastCalledWith('/price-watches/match', body, auth)
    await createPriceWatch(body, 'tok')
    expect(http.post).toHaveBeenLastCalledWith('/price-watches', body, auth)
    await updatePriceWatch(3, { status: 'paused' }, 'tok')
    expect(http.patch).toHaveBeenLastCalledWith('/price-watches/3', { status: 'paused' }, auth)
    await deletePriceWatch(3, 'tok')
    expect(http.delete).toHaveBeenLastCalledWith('/price-watches/3', auth)
    await checkPriceWatchNow(3, 'tok')
    expect(http.post).toHaveBeenLastCalledWith('/price-watches/3/check', null, auth)
  })
})
