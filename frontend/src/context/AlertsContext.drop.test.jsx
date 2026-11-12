// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'

const authState = { token: 'tok', user: { id: 5 } }
vi.mock('./AuthContext', () => ({ useAuth: () => authState }))
vi.mock('../services/api', () => ({
  getCapabilities: vi.fn(async () => ({ serpapi: true, fareWatch: true, email: false })),
  getUnreadCount: vi.fn(),
  listNotifications: vi.fn(),
  markNotificationsRead: vi.fn(),
  matchFareWatch: vi.fn(),
  matchPriceWatch: vi.fn(),
}))

import * as api from '../services/api'
import { AlertsProvider, useAlerts } from './AlertsContext'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

let seen
function Probe() { seen = useAlerts(); return null }
const drop = { from: 100, to: 90, amount: 10, pct: 10, currency: 'USD', target_hit: false, observed: true }
const note = (id, data = { drop }) => ({ id, kind: 'fare_drop', title: 't', body: 'b', data: { watch_id: 1, ...data }, read_at: null })

describe('AlertsContext drop moment state', () => {
  let container, root
  const mount = async () => { await act(async () => root.render(<AlertsProvider pollMs={60000}><Probe /></AlertsProvider>)) }

  beforeEach(() => {
    localStorage.clear()
    authState.user = { id: 5 }
    api.getUnreadCount.mockReset().mockResolvedValue(2)
    api.markNotificationsRead.mockReset()
    api.listNotifications.mockReset().mockResolvedValue({ items: [note(4), note(3, {}), note(2)] })
    container = document.createElement('div')
    root = createRoot(container)
  })
  afterEach(async () => { await act(async () => root.unmount()) })

  it('latestDrop is the newest unread note with a drop, ignoring notes without one', async () => {
    await mount()
    expect(seen.latestDrop.id).toBe(4)
  })

  it('shows once per notification per user', async () => {
    await mount()
    await act(async () => seen.markDropShown(4))
    expect(seen.latestDrop.id).toBe(2)
    expect(JSON.parse(localStorage.getItem('tp_drop_seen:5'))).toEqual([4])
    await act(async () => seen.markDropShown(2))
    expect(seen.latestDrop).toBeNull()
    // another user on the same device still sees them
    await act(async () => root.unmount())
    authState.user = { id: 6 }
    root = createRoot(container)
    await mount()
    expect(seen.latestDrop.id).toBe(4)
  })

  it('caps the stored ids at 50, keeping the newest', async () => {
    await mount()
    await act(async () => { for (let i = 1; i <= 60; i++) seen.markDropShown(i) })
    const ids = JSON.parse(localStorage.getItem('tp_drop_seen:5'))
    expect(ids).toHaveLength(50)
    expect(ids[49]).toBe(60)
    expect(ids[0]).toBe(11)
  })

  it('ignores estimates (observed false) and read notes', async () => {
    api.listNotifications.mockResolvedValue({ items: [note(8, { drop: { ...drop, observed: false } })] })
    await mount()
    expect(seen.latestDrop).toBeNull()
  })

  it('findDrop looks up an older drop by id', async () => {
    api.getUnreadCount.mockResolvedValue(0)
    api.listNotifications.mockResolvedValue({ items: [note(1)] })
    await mount()
    expect((await seen.findDrop(1)).id).toBe(1)
    expect(await seen.findDrop(99)).toBeNull()
  })
})
