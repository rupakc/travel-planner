// @vitest-environment node
import { describe, it, expect, vi, beforeEach } from 'vitest'

const http = vi.hoisted(() => ({ post: vi.fn(), get: vi.fn() }))
vi.mock('axios', () => ({ default: { create: () => http } }))

import {
  signup, verifyEmail, exchangeOAuthCode, changePasswordV2, resendVerification, confirmPasswordReset,
  requestPasswordReset, completeOAuthSignup, getLinkStartUrl, logoutAll,
} from './authApi'

beforeEach(() => { http.post.mockReset() })

describe('authApi', () => {
  it('sends client web and resolves with data', async () => {
    http.post.mockResolvedValue({ data: { status: 'verification_sent' } })
    expect(await signup({ username: 'jane' })).toEqual({ status: 'verification_sent' })
    expect(http.post.mock.calls[0][0]).toBe('/auth/signup')
    expect(http.post.mock.calls[0][1]).toMatchObject({ username: 'jane', client: 'web' })
  })
  it('rejects with a normalised error', async () => {
    http.post.mockRejectedValue({ response: { status: 410, data: { detail: 'old', error_code: 'token_expired' }, headers: {} } })
    await expect(verifyEmail('t')).rejects.toMatchObject({ status: 410, code: 'token_expired' })
  })
  it('exchange sends credentials', async () => {
    http.post.mockResolvedValue({ data: {} })
    await exchangeOAuthCode('c')
    expect(http.post.mock.calls[0][2]).toEqual({ withCredentials: true })
  })
  it('change password maps fields and bearer', async () => {
    http.post.mockResolvedValue({ data: {} })
    await changePasswordV2('tok', 'a', 'b')
    expect(http.post.mock.calls[0][1]).toMatchObject({ current_password: 'a', new_password: 'b' })
    expect(http.post.mock.calls[0][2].headers.Authorization).toBe('Bearer tok')
  })
  it('maps the remaining calls', async () => {
    http.post.mockResolvedValue({ data: { ok: 1 } })
    await resendVerification('a@b.c')
    expect(http.post.mock.calls.at(-1).slice(0, 2)).toEqual(['/auth/verify-email/resend', expect.objectContaining({ email: 'a@b.c', client: 'web' })])
    await requestPasswordReset('a@b.c')
    expect(http.post.mock.calls.at(-1)[0]).toBe('/auth/password-reset/request')
    await confirmPasswordReset('tk', 'newpw')
    expect(http.post.mock.calls.at(-1).slice(0, 2)).toEqual(['/auth/password-reset/confirm', expect.objectContaining({ token: 'tk', new_password: 'newpw' })])
    await completeOAuthSignup({ signup_token: 's', username: 'u' })
    expect(http.post.mock.calls.at(-1).slice(0, 2)).toEqual(['/auth/oauth/complete', expect.objectContaining({ signup_token: 's', username: 'u', client: 'web' })])
    await getLinkStartUrl('tok', 'github')
    const [p, b, c] = http.post.mock.calls.at(-1)
    expect(p).toBe('/auth/oauth/link-ticket')
    expect(b).toMatchObject({ provider: 'github' })
    expect(c.headers.Authorization).toBe('Bearer tok')
    await logoutAll('tok')
    expect(http.post.mock.calls.at(-1)[0]).toBe('/auth/logout-all')
    expect(http.post.mock.calls.at(-1)[2].headers.Authorization).toBe('Bearer tok')
  })
})
