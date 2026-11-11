// @vitest-environment node
import { describe, it, expect, vi, beforeEach } from 'vitest'

const http = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), patch: vi.fn(), put: vi.fn(), delete: vi.fn() }))
vi.mock('axios', () => ({ default: { create: () => http } }))

import * as api from './accountApi'

const auth = { headers: { Authorization: 'Bearer tok' } }
beforeEach(() => { for (const f of Object.values(http)) f.mockReset().mockResolvedValue({ data: { ok: 1 } }) })

describe('accountApi', () => {
  it('GET endpoints', async () => {
    await api.getAccount('tok'); expect(http.get).toHaveBeenLastCalledWith('/account', auth)
    await api.getSettings('tok'); expect(http.get).toHaveBeenLastCalledWith('/account/settings', auth)
    expect(await api.getQuota('tok')).toEqual({ ok: 1 })
    expect(http.get).toHaveBeenLastCalledWith('/account/quota', auth)
  })
  it('writes', async () => {
    await api.updateProfile('tok', { display_name: 'J' })
    expect(http.patch).toHaveBeenLastCalledWith('/account', { display_name: 'J' }, auth)
    await api.patchSettings('tok', { theme: 'dark' })
    expect(http.patch).toHaveBeenLastCalledWith('/account/settings', { theme: 'dark' }, auth)
    await api.putOnboarding('tok', { step: 1, done: false })
    expect(http.put).toHaveBeenLastCalledWith('/account/onboarding', { step: 1, done: false }, auth)
    await api.removeAvatar('tok')
    expect(http.delete).toHaveBeenLastCalledWith('/account/avatar', auth)
    await api.unlinkIdentity('tok', 'github')
    expect(http.delete).toHaveBeenLastCalledWith('/account/identities/github', auth)
    await api.deleteAccount('tok', { password: 'x' })
    expect(http.delete).toHaveBeenLastCalledWith('/account', { ...auth, data: { password: 'x' } })
    await api.requestEmailVerification('tok')
    expect(http.post.mock.calls.at(-1)[0]).toBe('/account/email/verify')
  })
  it('uploads the avatar as multipart field file', async () => {
    const file = new Blob(['x'], { type: 'image/png' })
    await api.uploadAvatar('tok', file)
    const [path, form, cfg] = http.put.mock.calls.at(-1)
    expect(path).toBe('/account/avatar')
    expect(form.get('file')).toBeTruthy()
    expect(cfg.headers.Authorization).toBe('Bearer tok')
  })
  it('export resolves a Blob', async () => {
    const blob = new Blob(['{}'])
    http.get.mockResolvedValue({ data: blob })
    expect(await api.exportAccount('tok')).toBe(blob)
    expect(http.get).toHaveBeenLastCalledWith('/account/export', { ...auth, responseType: 'blob' })
  })
  it('export decodes a Blob error body', async () => {
    const body = new Blob([JSON.stringify({ detail: 'Slow down', error_code: 'rate_limited' })])
    http.get.mockRejectedValue({ response: { status: 429, data: body, headers: { 'retry-after': '9' } } })
    await expect(api.exportAccount('tok')).rejects.toMatchObject({ status: 429, code: 'rate_limited', detail: 'Slow down', retryAfter: 9 })
  })
})
