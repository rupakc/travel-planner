// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import ModerationQueue from './ModerationQueue'
import AdminPage from '../../pages/AdminPage'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const api = vi.hoisted(() => ({ listQueue: vi.fn(), decide: vi.fn(), restrictUser: vi.fn(), liftRestriction: vi.fn() }))
const tel = vi.hoisted(() => ({ emit: vi.fn() }))
vi.mock('../../services/adminSocialApi', () => api)
vi.mock('../../telemetry/client', () => tel)
vi.mock('../../services/adminInvitesApi', () => ({ listInvites: vi.fn(() => Promise.reject({ status: 404 })) }))
vi.mock('../../services/api', () => ({ getTelemetrySummary: vi.fn(() => Promise.reject({ response: { status: 404 } })) }))
vi.mock('../../context/AuthContext', () => ({ useAuth: () => ({ token: 'tok', user: { username: 'root' } }) }))

const EVIL = '<img src=x onerror="alert(1)">'
const ITEM = { target: 'idea', id: '5', status: 'held', excerpt: EVIL, author_handle: 'ann', created_at: '2026-11-01T00:00:00Z', reason_counts: { spam: 2 } }
const flush = () => act(async () => { await new Promise(r => setTimeout(r, 0)) })

let root, host
beforeEach(() => {
  vi.clearAllMocks()
  vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve([]) })))
  api.listQueue.mockResolvedValue({ items: [ITEM], next: null })
  api.decide.mockResolvedValue({})
  api.restrictUser.mockResolvedValue({ until: 'x' })
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
})
afterEach(() => { vi.unstubAllGlobals(); act(() => root.unmount()); host.remove() })
const q = (tid) => host.querySelector(`[data-tid="${tid}"]`)

describe('ModerationQueue', () => {
  it('renders hostile text as plain text', async () => {
    await act(async () => root.render(<ModerationQueue token="tok" />))
    await flush()
    expect(host.querySelector('img')).toBeNull()
    expect(host.textContent).toContain(EVIL)
  })

  it('approves, removes the item and emits only the action', async () => {
    await act(async () => root.render(<ModerationQueue token="tok" />))
    await flush()
    await act(async () => { q('adminSocial.approve').click() })
    await flush()
    expect(api.decide).toHaveBeenCalledWith('tok', 'idea', '5', 'approve')
    expect(q('adminSocial.item')).toBeNull()
    expect(tel.emit).toHaveBeenCalledWith('admin_mod_action', { action: 'approve' })
  })

  it('restricts the author for the chosen days', async () => {
    await act(async () => root.render(<ModerationQueue token="tok" />))
    await flush()
    await act(async () => { q('adminSocial.restrict').click() })
    await flush()
    expect(api.restrictUser).toHaveBeenCalledWith('tok', 'ann', 7)
    expect(tel.emit).toHaveBeenCalledWith('admin_mod_action', { action: 'restrict' })
  })

  it('switches status and refetches', async () => {
    await act(async () => root.render(<ModerationQueue token="tok" />))
    await flush()
    await act(async () => { q('adminSocial.status-reported').click() })
    await flush()
    expect(api.listQueue).toHaveBeenLastCalledWith('tok', 'reported', undefined)
  })
})

describe('AdminPage Moderation tab', () => {
  it('is hidden on 404 and shown otherwise', async () => {
    api.listQueue.mockRejectedValue({ status: 404 })
    await act(async () => root.render(<AdminPage />))
    await flush()
    expect(q('admin.tab-Moderation')).toBeNull()
    act(() => root.unmount())
    root = createRoot(host)
    api.listQueue.mockResolvedValue({ items: [], next: null })
    await act(async () => root.render(<AdminPage />))
    await flush()
    expect(q('admin.tab-Moderation')).not.toBeNull()
  })
})
