import { describe, it, expect, vi, beforeEach } from 'vitest'

// A plain function (not vi.fn) stands in for axios.get: vitest's spy wrapper
// reports a rejecting call as an unhandled rejection even when it is caught.
const http = vi.hoisted(() => ({ calls: [], impl: null }))
vi.mock('axios', () => ({
  default: {
    create: () => ({
      get: (...args) => { http.calls.push(args); return http.impl() },
      post: () => {},
      interceptors: { request: { use: () => {} }, response: { use: () => {} } },
    }),
  },
}))

import { getAuthProviders } from './api'

beforeEach(() => { http.calls = []; http.impl = null })

describe('getAuthProviders', () => {
  it('returns the providers list', async () => {
    http.impl = async () => ({ data: { providers: [{ id: 'google', configured: false, start_url: null }] } })
    expect(await getAuthProviders()).toEqual([{ id: 'google', configured: false, start_url: null }])
    expect(http.calls).toEqual([['/auth/providers']])
  })

  it('never throws: a 404 yields an empty list', async () => {
    http.impl = async () => { throw { response: { status: 404 } } }
    await expect(getAuthProviders()).resolves.toEqual([])
  })

  it('never throws: a network error yields an empty list', async () => {
    http.impl = async () => { throw new Error('Network Error') }
    await expect(getAuthProviders()).resolves.toEqual([])
  })

  it('never throws: a malformed body yields an empty list', async () => {
    http.impl = async () => ({ data: {} })
    await expect(getAuthProviders()).resolves.toEqual([])
  })
})
