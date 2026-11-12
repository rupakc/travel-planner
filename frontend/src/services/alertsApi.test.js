// @vitest-environment node
import { describe, it, expect, vi, beforeEach } from 'vitest'

const http = vi.hoisted(() => ({
  get: vi.fn(), post: vi.fn(), put: vi.fn(),
  interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
}))
vi.mock('axios', () => ({ default: { create: () => http } }))

import {
  getSavings, getStory, requestAdvice, quickWatch, getSuggestions, getAlertPrefs, putAlertPrefs,
} from './alertsApi'

const auth = { headers: { Authorization: 'Bearer tok' } }

beforeEach(() => {
  for (const fn of ['get', 'post', 'put']) http[fn].mockReset().mockResolvedValue({ data: { ok: 1 } })
})

describe('alerts API', () => {
  it('reads the savings summary', async () => {
    expect(await getSavings('tok')).toEqual({ ok: 1 })
    expect(http.get).toHaveBeenLastCalledWith('/alerts/summary', auth)
  })

  it('reads a story and asks for advice per kind and id', async () => {
    await getStory('tok', 'hotel', 3)
    expect(http.get).toHaveBeenLastCalledWith('/alerts/watches/hotel/3/story', auth)
    await requestAdvice('tok', 'flight', 7)
    expect(http.post).toHaveBeenLastCalledWith('/alerts/watches/flight/7/advice', null, auth)
  })

  it('creates a quick watch', async () => {
    const body = { kind: 'hotel', title: 'x', spec: {}, surface: 'results' }
    await quickWatch('tok', body)
    expect(http.post).toHaveBeenLastCalledWith('/alerts/quick-watch', body, auth)
  })

  it('lists suggestions for a plan', async () => {
    await getSuggestions('tok', 9)
    expect(http.get).toHaveBeenLastCalledWith('/alerts/suggestions', { ...auth, params: { plan_id: 9 } })
  })

  it('gets and patches preferences', async () => {
    await getAlertPrefs('tok')
    expect(http.get).toHaveBeenLastCalledWith('/alerts/preferences', auth)
    await putAlertPrefs('tok', { digest_push: true })
    expect(http.put).toHaveBeenLastCalledWith('/alerts/preferences', { digest_push: true }, auth)
  })

  it('rejects with a normalised error', async () => {
    http.post.mockRejectedValue({ response: { status: 503, data: { detail: 'off', error_code: 'live_prices_off' }, headers: {} } })
    await expect(quickWatch('t', {})).rejects.toMatchObject({ status: 503, detail: 'off' })
  })
})
