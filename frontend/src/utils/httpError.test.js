import { describe, it, expect } from 'vitest'
import { responseErrorMessage } from './httpError'

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
