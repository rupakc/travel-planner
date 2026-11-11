// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
import { AuthProvider, useAuth } from './AuthContext'

beforeEach(() => {
  localStorage.clear()
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) }))
})

describe('applySession', () => {
  it('stores the token and sets the user', async () => {
    const { result } = renderHook(() => useAuth(), { wrapper: AuthProvider })
    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.accountVerified).toBe(true)
    let u
    await act(async () => { u = await result.current.applySession({ access_token: 'tok', user: { username: 'jane', account_verified: false } }) })
    expect(u.username).toBe('jane')
    expect(localStorage.getItem('tp_token')).toBe('tok')
    expect(result.current.user.username).toBe('jane')
    expect(result.current.accountVerified).toBe(false)
  })
})
