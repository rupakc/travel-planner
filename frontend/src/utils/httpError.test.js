import { describe, it, expect } from 'vitest'
import { responseErrorMessage, axiosErrorDetail, responseErrorInfo, errorCodeText } from './httpError'

const jsonResponse = (status, body) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

describe('responseErrorMessage', () => {
  it('shows the server string detail for a 429', async () => {
    const res = jsonResponse(429, { detail: 'Too many requests — please wait 42 seconds and try again.' })
    expect(await responseErrorMessage(res)).toBe('Too many requests — please wait 42 seconds and try again.')
  })

  it('falls back to the status when detail is not a string', async () => {
    const res = jsonResponse(422, { detail: [{ loc: ['body'], msg: 'bad' }] })
    expect(await responseErrorMessage(res)).toBe('HTTP 422')
  })

  it('falls back when the body is not JSON', async () => {
    expect(await responseErrorMessage(new Response('<html>oops</html>', { status: 502 }))).toBe('HTTP 502')
  })

  it('uses a caller-supplied fallback', async () => {
    expect(await responseErrorMessage(jsonResponse(500, {}), null)).toBeNull()
  })

  it('ignores a blank detail', async () => {
    expect(await responseErrorMessage(jsonResponse(429, { detail: '   ' }))).toBe('HTTP 429')
  })
})

describe('axiosErrorDetail', () => {
  const httpErr = (status, data) => Object.assign(new Error(`Request failed with status code ${status}`), { response: { status, data } })

  it('returns the string detail and status of a 429', () => {
    expect(axiosErrorDetail(httpErr(429, { detail: ' Too many requests — please wait 5 seconds and try again. ' })))
      .toEqual({ detail: 'Too many requests — please wait 5 seconds and try again.', status: 429 })
  })

  it('drops non-string or blank details but keeps the status', () => {
    expect(axiosErrorDetail(httpErr(422, { detail: [{ msg: 'bad' }] }))).toEqual({ detail: null, status: 422 })
    expect(axiosErrorDetail(httpErr(500, { detail: '  ' }))).toEqual({ detail: null, status: 500 })
    expect(axiosErrorDetail(httpErr(502, '<html>'))).toEqual({ detail: null, status: 502 })
  })

  it('handles network errors and non-errors', () => {
    expect(axiosErrorDetail(new Error('Network Error'))).toEqual({ detail: null, status: null })
    expect(axiosErrorDetail(undefined)).toEqual({ detail: null, status: null })
  })
})

describe('error_code translation (contract: render text from error_code, fall back to detail)', () => {
  it('translates a known error_code on fetch responses and axios errors', async () => {
    // The test setup initialises i18n, which registers its translator.
    const res = jsonResponse(429, { detail: "You've used today's AI allowance for search.", error_code: 'ai_daily_quota', bucket: 'search' })
    expect(await responseErrorMessage(res)).toBe("You've used today's AI allowance. It resets at midnight UTC.")
    const err = { response: { status: 403, data: { detail: 'server text', error_code: 'email_unverified' } } }
    expect(axiosErrorDetail(err)).toEqual({ detail: 'Confirm your email to use the AI planner.', status: 403 })
  })

  it('falls back to detail for an unknown code', async () => {
    const res = jsonResponse(503, { detail: 'AI limit reached', error_code: 'no_such_code_xyz' })
    expect(await responseErrorMessage(res)).toBe('AI limit reached')
    expect(errorCodeText('no_such_code_xyz')).toBeNull()
  })

  it('responseErrorInfo gives status, code and detail without translating', async () => {
    const res = jsonResponse(401, { detail: 'Signed out', error_code: 'session_revoked' })
    expect(await responseErrorInfo(res)).toEqual({ status: 401, code: 'session_revoked', detail: 'Signed out' })
    expect(await responseErrorInfo(new Response('x', { status: 502 }))).toEqual({ status: 502, code: null, detail: null })
  })
})
