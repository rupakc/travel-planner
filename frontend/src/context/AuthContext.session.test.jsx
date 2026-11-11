// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { AuthProvider, useAuth } from './AuthContext'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

let auth
function Probe() { auth = useAuth(); return null }

beforeEach(() => {
  localStorage.clear()
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) }))
})

describe('applySession', () => {
  it('stores the token and sets the user', async () => {
    const root = createRoot(document.createElement('div'))
    await act(async () => { root.render(<AuthProvider><Probe /></AuthProvider>) })
    expect(auth.accountVerified).toBe(true)
    let u
    await act(async () => { u = await auth.applySession({ access_token: 'tok', user: { username: 'jane', account_verified: false } }) })
    expect(u.username).toBe('jane')
    expect(localStorage.getItem('tp_token')).toBe('tok')
    expect(auth.user.username).toBe('jane')
    expect(auth.accountVerified).toBe(false)
    act(() => root.unmount())
  })
})

describe('session_revoked', () => {
  it('signs out with a reason when a request reports session_revoked, and a new session clears it', async () => {
    const { reportSessionRevoked } = await import('../services/sessionRevoked')
    const root = createRoot(document.createElement('div'))
    await act(async () => { root.render(<AuthProvider><Probe /></AuthProvider>) })
    await act(async () => { await auth.applySession({ access_token: 'tok', user: { username: 'jane' } }) })
    expect(auth.signOutReason).toBeNull()
    act(() => reportSessionRevoked())
    expect(auth.user).toBeNull()
    expect(auth.token).toBeNull()
    expect(localStorage.getItem('tp_token')).toBeNull()
    expect(auth.signOutReason).toBe('session_revoked')
    await act(async () => { await auth.applySession({ access_token: 'tok2', user: { username: 'jane' } }) })
    expect(auth.signOutReason).toBeNull()
    act(() => root.unmount())
  })

  it('ignores a report when nobody is signed in', async () => {
    const { reportSessionRevoked } = await import('../services/sessionRevoked')
    const root = createRoot(document.createElement('div'))
    await act(async () => { root.render(<AuthProvider><Probe /></AuthProvider>) })
    act(() => reportSessionRevoked())
    expect(auth.signOutReason).toBeNull()
    act(() => root.unmount())
  })

  it('keeps the reason when the stored token is already revoked on load', async () => {
    localStorage.setItem('tp_token', 'old')
    fetch.mockResolvedValue({ ok: false, status: 401, json: async () => ({ detail: 'x', error_code: 'session_revoked' }) })
    const root = createRoot(document.createElement('div'))
    await act(async () => { root.render(<AuthProvider><Probe /></AuthProvider>) })
    expect(localStorage.getItem('tp_token')).toBeNull()
    expect(auth.signOutReason).toBe('session_revoked')
    act(() => root.unmount())
  })
})
