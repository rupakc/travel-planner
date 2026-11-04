// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act, StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

const authState = { token: 'tok' }
vi.mock('./AuthContext', () => ({ useAuth: () => authState }))
vi.mock('../services/api', () => ({
  getCapabilities: vi.fn(async () => ({ serpapi: true, fareWatch: true, email: false })),
  getUnreadCount: vi.fn(),
  listNotifications: vi.fn(),
  markNotificationsRead: vi.fn(),
  matchFareWatch: vi.fn(),
}))

import * as api from '../services/api'
import { AlertsProvider, useAlerts } from './AlertsContext'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

let seen
function Probe() {
  seen = useAlerts()
  return null
}

const note = (id, over = {}) => ({ id, kind: 'fare_drop', title: `Drop ${id}`, body: 'b', data: { watch_id: 1 }, read_at: null, ...over })

describe('AlertsProvider', () => {
  let container, root, visibility

  const mount = async () => {
    await act(async () => root.render(<AlertsProvider pollMs={60000}><Probe /></AlertsProvider>))
  }
  const tick = async (ms) => { await act(async () => { vi.advanceTimersByTime(ms) }) }
  const setVisibility = async (v) => {
    visibility = v
    await act(async () => document.dispatchEvent(new Event('visibilitychange')))
  }

  beforeEach(() => {
    vi.useFakeTimers()
    visibility = 'visible'
    Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => visibility })
    vi.spyOn(document, 'hasFocus').mockReturnValue(true)
    api.getUnreadCount.mockReset().mockResolvedValue(0)
    api.listNotifications.mockReset().mockResolvedValue({ items: [] })
    api.markNotificationsRead.mockReset().mockResolvedValue({ updated: 1, unread: 0 })
    container = document.createElement('div')
    root = createRoot(container)
  })

  afterEach(() => {
    act(() => root.unmount())
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('polls the unread count every minute while visible', async () => {
    await mount()
    expect(api.getUnreadCount).toHaveBeenCalledTimes(1)
    await tick(60000)
    await tick(60000)
    expect(api.getUnreadCount).toHaveBeenCalledTimes(3)
  })

  it('stops polling while the tab is hidden and refreshes on return', async () => {
    await mount()
    await setVisibility('hidden')
    await tick(5 * 60000)
    expect(api.getUnreadCount).toHaveBeenCalledTimes(1)
    await setVisibility('visible')
    expect(api.getUnreadCount).toHaveBeenCalledTimes(2)
    await tick(60000)
    expect(api.getUnreadCount).toHaveBeenCalledTimes(3)
  })

  it('does not toast notifications that existed before the app opened', async () => {
    api.getUnreadCount.mockResolvedValue(2)
    api.listNotifications.mockResolvedValue({ items: [note(9), note(8)] })
    await mount()
    expect(seen.unread).toBe(2)
    expect(seen.toast).toBeNull()
  })

  it('toasts a new notification once, the newest only', async () => {
    await mount()
    api.getUnreadCount.mockResolvedValue(2)
    api.listNotifications.mockResolvedValue({ items: [note(12), note(11)] })
    await tick(60000)
    expect(seen.unread).toBe(2)
    expect(seen.toast.id).toBe(12)
    act(() => seen.dismissToast())
    await tick(60000) // same count, nothing new
    expect(seen.toast).toBeNull()
  })

  it('uses a native notification instead when the window is unfocused and allowed', async () => {
    const shown = []
    class FakeNotification {
      static permission = 'granted'
      constructor(title, opts) { shown.push({ title, ...opts }) }
    }
    vi.stubGlobal('Notification', FakeNotification)
    document.hasFocus.mockReturnValue(false)
    await mount()
    api.getUnreadCount.mockResolvedValue(1)
    api.listNotifications.mockResolvedValue({ items: [note(20)] })
    await tick(60000)
    expect(shown).toEqual([{ title: 'Drop 20', body: 'b', tag: 'fare-alert-20' }])
    expect(seen.toast).toBeNull()
    vi.unstubAllGlobals()
  })

  it('markSeen keeps an alert the user already saw from becoming a toast', async () => {
    await mount()
    act(() => seen.markSeen(30))
    api.getUnreadCount.mockResolvedValue(1)
    api.listNotifications.mockResolvedValue({ items: [note(30)] })
    await tick(60000)
    expect(seen.unread).toBe(1)
    expect(seen.toast).toBeNull()
  })

  it('starts fresh for a different account (no toasts for its old alerts)', async () => {
    await mount()
    authState.token = 'other'
    api.getUnreadCount.mockResolvedValue(4)
    api.listNotifications.mockResolvedValue({ items: [note(99)] })
    await act(async () => root.render(<AlertsProvider pollMs={60000}><Probe /></AlertsProvider>))
    expect(seen.unread).toBe(4)
    expect(seen.toast).toBeNull()
    authState.token = 'tok'
  })

  it('a focus and a visibility change together refresh once', async () => {
    await mount()
    api.getUnreadCount.mockClear()
    await setVisibility('hidden')
    await act(async () => {
      visibility = 'visible'
      document.dispatchEvent(new Event('visibilitychange'))
      window.dispatchEvent(new Event('focus'))
    })
    expect(api.getUnreadCount).toHaveBeenCalledTimes(1)
  })

  it('markRead updates the unread count', async () => {
    api.getUnreadCount.mockResolvedValue(3)
    api.listNotifications.mockResolvedValue({ items: [note(1)] })
    await mount()
    api.markNotificationsRead.mockResolvedValue({ updated: 3, unread: 0 })
    await act(async () => seen.markRead('all'))
    expect(api.markNotificationsRead).toHaveBeenCalledWith('all', 'tok')
    expect(seen.unread).toBe(0)
  })

  it('offers browser alerts once, only while permission is undecided', async () => {
    const requestPermission = vi.fn(async () => 'granted')
    vi.stubGlobal('Notification', { permission: 'default', requestPermission })
    localStorage.clear()
    await mount()
    expect(seen.shouldOfferBrowserAlerts()).toBe(true)
    await act(async () => seen.answerBrowserAlerts(false))
    expect(requestPermission).not.toHaveBeenCalled()
    expect(seen.shouldOfferBrowserAlerts()).toBe(false)
    vi.unstubAllGlobals()
  })
})

describe('AlertsProvider under StrictMode', () => {
  let container, root, visibility
  const strict = (props = {}) => (
    <StrictMode><AlertsProvider pollMs={60000} {...props}><Probe /></AlertsProvider></StrictMode>
  )
  const tick = async (ms) => { await act(async () => { vi.advanceTimersByTime(ms) }) }

  beforeEach(() => {
    vi.useFakeTimers()
    visibility = 'visible'
    Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => visibility })
    vi.spyOn(document, 'hasFocus').mockReturnValue(true)
    api.getUnreadCount.mockReset().mockResolvedValue(0)
    api.listNotifications.mockReset().mockResolvedValue({ items: [] })
    authState.token = 'tok'
    container = document.createElement('div')
    root = createRoot(container)
  })
  afterEach(() => {
    act(() => root.unmount())
    vi.useRealTimers()
    vi.restoreAllMocks()
    authState.token = 'tok'
  })

  it('polls once on mount and once a minute, despite double effects', async () => {
    await act(async () => root.render(strict()))
    expect(api.getUnreadCount).toHaveBeenCalledTimes(1)
    await tick(60000)
    expect(api.getUnreadCount).toHaveBeenCalledTimes(2)
  })

  it('never toasts alerts that existed before load, toasts a new one once', async () => {
    api.getUnreadCount.mockResolvedValue(2)
    api.listNotifications.mockResolvedValue({ items: [note(9), note(8)] })
    await act(async () => root.render(strict()))
    expect(seen.toast).toBeNull()
    api.getUnreadCount.mockResolvedValue(3)
    api.listNotifications.mockResolvedValue({ items: [note(10), note(9)] })
    await tick(60000)
    expect(seen.toast.id).toBe(10)
    act(() => seen.dismissToast())
    await tick(60000)
    expect(seen.toast).toBeNull()
  })

  it('starts fresh for another account', async () => {
    await act(async () => root.render(strict()))
    authState.token = 'other'
    api.getUnreadCount.mockResolvedValue(4)
    api.listNotifications.mockResolvedValue({ items: [note(99)] })
    await act(async () => root.render(strict()))
    expect(seen.unread).toBe(4)
    expect(seen.toast).toBeNull()
  })

  it('opens a native notification with the latest onOpenLink', async () => {
    let made
    class FakeNotification {
      static permission = 'granted'
      constructor() { made = this }
      close() {}
    }
    vi.stubGlobal('Notification', FakeNotification)
    document.hasFocus.mockReturnValue(false)
    const first = vi.fn()
    const second = vi.fn()
    await act(async () => root.render(strict({ onOpenLink: first })))
    await act(async () => root.render(strict({ onOpenLink: second })))
    api.getUnreadCount.mockResolvedValue(1)
    api.listNotifications.mockResolvedValue({ items: [note(5)] })
    await tick(60000)
    vi.spyOn(window, 'focus').mockImplementation(() => {})
    made.onclick()
    expect(second).toHaveBeenCalledWith(expect.objectContaining({ id: 5 }))
    expect(first).not.toHaveBeenCalled()
    vi.unstubAllGlobals()
  })
})

describe('useAlerts outside the provider', () => {
  it('is inert: nothing available, nothing unread', () => {
    const container = document.createElement('div')
    const root = createRoot(container)
    act(() => root.render(<Probe />))
    expect(seen.unread).toBe(0)
    expect(seen.caps.fareWatch).toBe(false)
    act(() => root.unmount())
  })
})
