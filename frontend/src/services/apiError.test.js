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

describe('errorText with the real catalogue', () => {
  it('falls back to detail for an unknown code instead of showing the code', async () => {
    const { default: i18n } = await import('../i18n')
    const t = i18n.getFixedT('en')
    expect(errorText(t, { code: 'ai_limit_xyz', detail: 'AI limit reached' })).toBe('AI limit reached')
    expect(errorText(t, { code: 'email_unverified', detail: 'x' })).toBe('Confirm your email to use the AI planner.')
  })
})
