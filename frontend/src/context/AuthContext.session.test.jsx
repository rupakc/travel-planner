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
    act(() => reportSessionRevoked('tok'))
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
  it('ignores a late answer for an older token', async () => {
    const { reportSessionRevoked } = await import('../services/sessionRevoked')
    const root = createRoot(document.createElement('div'))
    await act(async () => { root.render(<AuthProvider><Probe /></AuthProvider>) })
    await act(async () => { await auth.applySession({ access_token: 'new', user: { username: 'jane' } }) })
    act(() => reportSessionRevoked('old'))
    expect(auth.token).toBe('new')
    expect(auth.user.username).toBe('jane')
    expect(localStorage.getItem('tp_token')).toBe('new')
    expect(auth.signOutReason).toBeNull()
    act(() => root.unmount())
  })

  it('signs out when its own token is revoked even though another tab already cleared storage', async () => {
    const { reportSessionRevoked } = await import('../services/sessionRevoked')
    const root = createRoot(document.createElement('div'))
    await act(async () => { root.render(<AuthProvider><Probe /></AuthProvider>) })
    await act(async () => { await auth.applySession({ access_token: 'tokA', user: { username: 'jane' } }) })
    localStorage.removeItem('tp_token') // tab B ran "sign out everywhere"
    act(() => reportSessionRevoked('tokA'))
    expect(auth.user).toBeNull()
    expect(auth.token).toBeNull()
    expect(auth.signOutReason).toBe('session_revoked')
    act(() => root.unmount())
  })

  it("adopts the fresh token another tab stored, and never deletes it", async () => {
    const { reportSessionRevoked } = await import('../services/sessionRevoked')
    const root = createRoot(document.createElement('div'))
    await act(async () => { root.render(<AuthProvider><Probe /></AuthProvider>) })
    await act(async () => { await auth.applySession({ access_token: 'tokA', user: { username: 'jane' } }) })
    localStorage.setItem('tp_token', 'tokB') // tab B reset the password
    fetch.mockImplementation(async (url, init) => {
      if (url === '/api/auth/me' && init.headers.Authorization === 'Bearer tokB') {
        return { ok: true, status: 200, json: async () => ({ username: 'jane', display_name: 'Jane B' }) }
      }
      return { ok: true, status: 200, json: async () => ({}) }
    })
    await act(async () => { reportSessionRevoked('tokA') })
    expect(localStorage.getItem('tp_token')).toBe('tokB')
    expect(auth.token).toBe('tokB')
    expect(auth.user.display_name).toBe('Jane B')
    expect(auth.signOutReason).toBeNull()
    act(() => root.unmount())
  })

  it('a stale mount-time /auth/me does not undo a newer session', async () => {
    localStorage.setItem('tp_token', 'dead')
    let rejectMe
    fetch.mockImplementation((url, init) => {
      if (url === '/api/auth/me' && init.headers.Authorization === 'Bearer dead') {
        return new Promise((resolve) => { rejectMe = () => resolve({ ok: false, status: 401, json: async () => ({ error_code: 'session_revoked' }) }) })
      }
      return Promise.resolve({ ok: true, status: 200, json: async () => ({}) })
    })
    const root = createRoot(document.createElement('div'))
    await act(async () => { root.render(<AuthProvider><Probe /></AuthProvider>) })
    await act(async () => { await auth.applySession({ access_token: 'fresh', user: { username: 'bob' } }) })
    await act(async () => { rejectMe() })
    expect(localStorage.getItem('tp_token')).toBe('fresh')
    expect(auth.token).toBe('fresh')
    expect(auth.user.username).toBe('bob')
    expect(auth.signOutReason).toBeNull()
    act(() => root.unmount())
  })
})
