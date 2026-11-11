// @vitest-environment node
import { describe, it, expect } from 'vitest'
import { toApiError, errorText } from './apiError'

const axiosErr = (status, data, headers = {}) => ({ response: { status, data, headers } })

describe('toApiError', () => {
  it('reads code, extras and Retry-After', () => {
    expect(toApiError(axiosErr(429, { detail: 'Used up', error_code: 'ai_daily_quota', bucket: 'search' }, { 'retry-after': '30' })))
      .toEqual({ status: 429, code: 'ai_daily_quota', detail: 'Used up', retryAfter: 30, extra: { bucket: 'search' } })
  })
  it('takes the first message of a FastAPI 422 list', () => {
    const e = toApiError(axiosErr(422, { detail: [{ msg: 'field required', loc: ['body'] }] }))
    expect(e.code).toBeNull()
    expect(e.detail).toBe('field required')
    expect(e.retryAfter).toBeNull()
  })
  it('handles a network error', () => {
    expect(toApiError(new Error('Network Error'))).toMatchObject({ status: 0, code: null, detail: 'Network Error' })
  })
})

describe('errorText', () => {
  const t = (key, o) => (key === 'errors:known' ? 'Known text' : key === 'errors:generic' ? 'Generic' : o?.defaultValue ?? key)
  it('uses the catalogue, then detail, then generic', () => {
    expect(errorText(t, { code: 'known', detail: 'x' })).toBe('Known text')
    expect(errorText(t, { code: 'unknown', detail: 'Server said' })).toBe('Server said')
    expect(errorText(t, { code: null, detail: '' })).toBe('Generic')
  })
})

describe('session_revoked', () => {
  it('notifies onSessionRevoked listeners for a 401 session_revoked only', async () => {
    const { onSessionRevoked } = await import('./sessionRevoked')
    let calls = 0
    const off = onSessionRevoked(() => { calls += 1 })
    toApiError(axiosErr(401, { detail: 'Signed out', error_code: 'session_revoked' }))
    expect(calls).toBe(1)
    toApiError(axiosErr(401, { detail: 'Invalid or expired token' }))
    toApiError(axiosErr(403, { detail: 'x', error_code: 'session_revoked' }))
    expect(calls).toBe(1)
    off()
    toApiError(axiosErr(401, { detail: 'Signed out', error_code: 'session_revoked' }))
    expect(calls).toBe(1)
  })
})
