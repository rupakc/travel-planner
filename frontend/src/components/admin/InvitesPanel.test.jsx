// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import InvitesPanel from './InvitesPanel'
import AdminPage from '../../pages/AdminPage'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const api = vi.hoisted(() => ({ listInvites: vi.fn(), createInvite: vi.fn(), revokeInvite: vi.fn() }))
vi.mock('../../services/adminInvitesApi', () => api)
vi.mock('../../services/api', () => ({ getTelemetrySummary: vi.fn(() => Promise.reject({ response: { status: 404 } })) }))
vi.mock('../../context/AuthContext', () => ({ useAuth: () => ({ token: 'tok', user: { username: 'root' } }) }))

const ROW = { id: 7, code_prefix: 'VOY-ABCD', max_uses: 5, uses: 2, expires_at: '2099-01-01T00:00:00Z', revoked_at: null, note: 'friends', created_at: '2026-11-01T00:00:00Z' }
const flush = () => act(async () => { await new Promise(r => setTimeout(r, 0)) })

let root, host
beforeEach(() => {
  vi.clearAllMocks()
  vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve([]) })))
  api.listInvites.mockResolvedValue([ROW])
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
})
afterEach(() => { vi.unstubAllGlobals(); act(() => root.unmount()); host.remove() })

const q = (tid) => host.querySelector(`[data-tid="${tid}"]`)

describe('InvitesPanel', () => {
  it('shows a created code once and not after a reload', async () => {
    api.createInvite.mockResolvedValue({ ...ROW, id: 8, code: 'VOY-ABCD-WXYZ' })
    await act(async () => root.render(<InvitesPanel token="tok" />))
    await flush()
    expect(host.textContent).toContain('VOY-ABCD…')
    await act(async () => { q('adminInvites.create').click() })
    await flush()
    expect(api.createInvite).toHaveBeenCalledWith('tok', { max_uses: 1, expires_in_days: 14 })
    expect(q('adminInvites.code').textContent).toBe('VOY-ABCD-WXYZ')
    await act(async () => root.unmount())
    root = createRoot(host)
    await act(async () => root.render(<InvitesPanel token="tok" />))
    await flush()
    expect(host.textContent).not.toContain('VOY-ABCD-WXYZ')
    expect(q('adminInvites.code')).toBeNull()
  })

  it('revokes an active invite', async () => {
    api.revokeInvite.mockResolvedValue(null)
    await act(async () => root.render(<InvitesPanel token="tok" />))
    await flush()
    await act(async () => { q('adminInvites.revoke').click() })
    await flush()
    expect(api.revokeInvite).toHaveBeenCalledWith('tok', 7)
    expect(api.listInvites).toHaveBeenCalledTimes(2)
  })
})

describe('InvitesPanel remount', () => {
  it('refetches on remount instead of reusing the seeded list', async () => {
    await act(async () => root.render(<InvitesPanel token="tok" initial={[ROW]} />))
    await flush()
    expect(api.listInvites).toHaveBeenCalledTimes(1)
    api.listInvites.mockResolvedValue([{ ...ROW, id: 9, code_prefix: 'VOY-NEWW' }])
    await act(async () => root.unmount())
    root = createRoot(host)
    await act(async () => root.render(<InvitesPanel token="tok" initial={[ROW]} />))
    await flush()
    expect(api.listInvites).toHaveBeenCalledTimes(2)
    expect(host.textContent).toContain('VOY-NEWW')
    expect(host.textContent).not.toContain('VOY-ABCD')
  })
})

describe('AdminPage invites tab', () => {
  it('is hidden when GET /admin/invites is 404', async () => {
    api.listInvites.mockRejectedValue({ status: 404 })
    await act(async () => root.render(<AdminPage />))
    await flush()
    expect(q('admin.tab-Invites')).toBeNull()
  })

  it('is shown when the endpoint exists', async () => {
    await act(async () => root.render(<AdminPage />))
    await flush()
    expect(q('admin.tab-Invites')).not.toBeNull()
  })
})
