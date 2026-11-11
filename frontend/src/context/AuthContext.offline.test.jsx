// @vitest-environment jsdom
// Opening the app offline keeps the session; a real 401 still signs out;
// signing out deletes only that user's offline data.
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'

const config = vi.hoisted(() => ({ value: {} }))
const disableOffline = vi.hoisted(() => vi.fn(async () => {}))
vi.mock('../hooks/useClientConfig', async (orig) => ({
  ...(await orig()),
  loadClientConfig: () => Promise.resolve(config.value),
}))
vi.mock('../offline/registerSW', async (orig) => ({ ...(await orig()), disableOffline }))

import { AuthProvider, useAuth } from './AuthContext'
import { savePack, listPacks } from '../offline/packStore'
import { enqueue, pending } from '../offline/outbox'
import { _resetForTests } from '../offline/idb'
import { reportSessionRevoked } from '../services/sessionRevoked'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const JANE = { id: 7, username: 'jane', display_name: 'Jane', is_admin: false, email: 'j@x.test' }

// A JWT-shaped token whose payload carries uid/sub (the signature is never checked client-side).
const b64 = (o) => btoa(JSON.stringify(o)).replace(/=+$/, '').replace(/\+/g, '-').replace(/\//g, '_')
const tokenFor = (uid, sub) => `${b64({ alg: 'HS256' })}.${b64({ uid, sub })}.sig`

let auth
function Probe() { auth = useAuth(); return null }

async function mount() {
  const root = createRoot(document.createElement('div'))
  await act(async () => { root.render(<AuthProvider><Probe /></AuthProvider>) })
  await act(async () => { await new Promise((r) => setTimeout(r, 0)) })
  return root
}

const answer = (status, body) => ({ ok: status >= 200 && status < 300, status, json: async () => body })

beforeEach(() => {
  localStorage.clear()
  _resetForTests()
  config.value = {}
  disableOffline.mockClear()
})

describe('AuthContext offline', () => {
  it('keeps the session when /auth/me fails offline', async () => {
    const tok = tokenFor(7, 'jane')
    localStorage.setItem('tp_token', tok)
    localStorage.setItem('tp_user_cache', JSON.stringify({ id: 7, username: 'jane', display_name: 'Jane', is_admin: false }))
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    const root = await mount()
    expect(auth.loading).toBe(false)
    expect(auth.token).toBe(tok)
    expect(localStorage.getItem('tp_token')).toBe(tok)
    expect(auth.user).toEqual({ id: 7, username: 'jane', display_name: 'Jane', is_admin: false })
    expect(auth.isAuthenticated).toBe(true)
    expect(auth.offline).toBe(true)

    // back online: revalidates and leaves the offline state
    fetch.mockImplementation(async (url) => (url === '/api/auth/me' ? answer(200, JANE) : answer(200, { theme: 'dark' })))
    await act(async () => { window.dispatchEvent(new Event('online')) })
    await act(async () => { await new Promise((r) => setTimeout(r, 0)) })
    expect(auth.offline).toBe(false)
    expect(auth.user.email).toBe('j@x.test')
    act(() => root.unmount())
  })

  it('keeps the token (no user) when nothing is cached, and never restores a cache for another account', async () => {
    const tok = tokenFor(8, 'bob')
    localStorage.setItem('tp_token', tok)
    localStorage.setItem('tp_user_cache', JSON.stringify({ id: 7, username: 'jane', display_name: 'Jane', is_admin: false }))
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    const root = await mount()
    expect(auth.token).toBe(tok)
    expect(auth.user).toBeNull()
    expect(auth.offline).toBe(true)
    act(() => root.unmount())
  })

  it('writes tp_user_cache on a successful load', async () => {
    localStorage.setItem('tp_token', tokenFor(7, 'jane'))
    vi.stubGlobal('fetch', vi.fn(async (url) => (url === '/api/auth/me' ? answer(200, JANE) : answer(200, {}))))
    const root = await mount()
    expect(JSON.parse(localStorage.getItem('tp_user_cache'))).toEqual({ id: 7, username: 'jane', display_name: 'Jane', is_admin: false })
    expect(auth.offline).toBe(false)
    act(() => root.unmount())
  })

  it('a failed preferences load does not sign out', async () => {
    localStorage.setItem('tp_token', 'tok')
    vi.stubGlobal('fetch', vi.fn(async (url) => {
      if (url === '/api/auth/me') return answer(200, JANE)
      throw new TypeError('Failed to fetch')
    }))
    const root = await mount()
    expect(auth.user.username).toBe('jane')
    expect(auth.token).toBe('tok')
    act(() => root.unmount())
  })

  it('a 401 still signs out', async () => {
    localStorage.setItem('tp_token', 'tok')
    localStorage.setItem('tp_user_cache', JSON.stringify({ id: 7, username: 'jane', display_name: 'Jane', is_admin: false }))
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(answer(401, { detail: 'expired' })))
    const root = await mount()
    expect(auth.token).toBeNull()
    expect(auth.user).toBeNull()
    expect(auth.offline).toBe(false)
    expect(localStorage.getItem('tp_token')).toBeNull()
    expect(localStorage.getItem('tp_user_cache')).toBeNull()
    act(() => root.unmount())
  })

  it('a 403 still signs out', async () => {
    localStorage.setItem('tp_token', 'tok')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(answer(403, { detail: 'inactive' })))
    const root = await mount()
    expect(auth.token).toBeNull()
    expect(auth.user).toBeNull()
    act(() => root.unmount())
  })

  it("logout clears that user's packs and outbox but not another user's", async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(answer(200, {})))
    const root = await mount()
    await act(async () => { await auth.applySession({ access_token: 'tok', user: JANE }) })
    expect(localStorage.getItem('tp_user_cache')).not.toBeNull()
    await savePack(7, { trip_id: 12 })
    await savePack(9, { trip_id: 3 })
    await enqueue(7, { method: 'POST', path: '/trips/12/journal', body: {}, key: 'a' })
    await enqueue(9, { method: 'POST', path: '/trips/3/journal', body: {}, key: 'a' })
    await act(async () => { await auth.logout() })
    expect(auth.user).toBeNull()
    expect(localStorage.getItem('tp_user_cache')).toBeNull()
    expect(await listPacks(7)).toEqual([])
    expect(await pending(7)).toBe(0)
    expect(await listPacks(9)).toHaveLength(1)
    expect(await pending(9)).toBe(1)
    act(() => root.unmount())
  })

  it("session_revoked clears that user's offline data", async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(answer(200, {})))
    const root = await mount()
    await act(async () => { await auth.applySession({ access_token: 'tok', user: JANE }) })
    await savePack(7, { trip_id: 12 })
    await enqueue(7, { method: 'POST', path: '/trips/12/journal', body: {}, key: 'a' })
    act(() => reportSessionRevoked('tok'))
    await act(async () => { await new Promise((r) => setTimeout(r, 0)) })
    expect(auth.user).toBeNull()
    expect(localStorage.getItem('tp_user_cache')).toBeNull()
    expect(await listPacks(7)).toEqual([])
    expect(await pending(7)).toBe(0)
    act(() => root.unmount())
  })

  it('offline_pack false → disableOffline is called (once)', async () => {
    config.value = { features: { trips: true, offline_pack: false } }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(answer(200, {})))
    const a = await mount()
    const b = await mount()
    expect(disableOffline).toHaveBeenCalledTimes(1)
    act(() => { a.unmount(); b.unmount() })
  })
})

describe('AuthContext offline flag', () => {
  it('never disables offline when the flag is on or missing', async () => {
    config.value = { features: { trips: true, offline_pack: true } }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(answer(200, {})))
    const root = await mount()
    expect(disableOffline).not.toHaveBeenCalled()
    act(() => root.unmount())
  })
})
