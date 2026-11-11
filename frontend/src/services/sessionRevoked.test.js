// @vitest-environment node
import { describe, it, expect, vi, afterEach } from 'vitest'
import axios from 'axios'
import { onSessionRevoked, bearerToken, watchAxios, watchFetch, isSessionRevoked } from './sessionRevoked'

const json = (status, body) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
const flush = () => new Promise((r) => setTimeout(r, 0))

let off = () => {}
afterEach(() => off())

function listen() {
  const seen = []
  off = onSessionRevoked((tok) => seen.push(tok))
  return seen
}

describe('bearerToken', () => {
  it('reads plain objects, Headers and AxiosHeaders', () => {
    expect(bearerToken({ Authorization: 'Bearer abc' })).toBe('abc')
    expect(bearerToken(new Headers({ authorization: 'Bearer xyz' }))).toBe('xyz')
    expect(bearerToken(axios.AxiosHeaders.from({ Authorization: 'Bearer q1' }))).toBe('q1')
    expect(bearerToken({ 'Content-Type': 'application/json' })).toBeNull()
    expect(bearerToken(null)).toBeNull()
  })
})

describe('isSessionRevoked', () => {
  it('is only a 401 with the code', () => {
    expect(isSessionRevoked(401, { error_code: 'session_revoked' })).toBe(true)
    expect(isSessionRevoked(403, { error_code: 'session_revoked' })).toBe(false)
    expect(isSessionRevoked(401, { detail: 'Invalid or expired token' })).toBe(false)
  })
})

describe('watchAxios', () => {
  it('reports a 401 session_revoked with the token the request used, and still rejects', async () => {
    const seen = listen()
    const http = watchAxios(axios.create({ baseURL: 'http://x' }))
    http.defaults.adapter = async (config) => {
      const err = new Error('401')
      err.config = config
      err.response = { status: 401, data: { detail: 'Signed out', error_code: 'session_revoked' }, headers: {}, config }
      throw err
    }
    await expect(http.get('/a', { headers: { Authorization: 'Bearer tokA' } })).rejects.toThrow('401')
    expect(seen).toEqual(['tokA'])
  })

  it('ignores other failures', async () => {
    const seen = listen()
    const http = watchAxios(axios.create({ baseURL: 'http://x' }))
    http.defaults.adapter = async (config) => {
      const err = new Error('401')
      err.config = config
      err.response = { status: 401, data: { detail: 'Invalid or expired token' }, headers: {}, config }
      throw err
    }
    await expect(http.get('/a')).rejects.toThrow()
    expect(seen).toEqual([])
  })

  it('leaves a stubbed instance alone', () => {
    const stub = { get: vi.fn() }
    expect(watchAxios(stub)).toBe(stub)
  })
})

describe('watchFetch', () => {
  it('reports from a clone, so the caller still reads the body', async () => {
    const seen = listen()
    const target = { fetch: vi.fn(async () => json(401, { detail: 'Signed out', error_code: 'session_revoked' })) }
    watchFetch(target)
    watchFetch(target) // idempotent
    const res = await target.fetch('/api/plans', { headers: { Authorization: 'Bearer tokF' } })
    expect((await res.json()).error_code).toBe('session_revoked')
    await flush()
    expect(seen).toEqual(['tokF'])
    expect(target.fetch.__tpSessionWatch).toBe(true)
  })

  it('does not report other responses', async () => {
    const seen = listen()
    const target = { fetch: vi.fn(async () => json(401, { detail: 'Invalid or expired token' })) }
    watchFetch(target)
    await target.fetch('/api/x', { headers: { Authorization: 'Bearer t' } })
    target.fetch = vi.fn(async () => json(200, { ok: true }))
    await flush()
    expect(seen).toEqual([])
  })
})
