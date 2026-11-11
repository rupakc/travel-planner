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
