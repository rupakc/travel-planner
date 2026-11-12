// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'

vi.mock('../../context/AuthContext', () => ({ useAuth: () => ({ token: 'tok' }) }))
const cfg = vi.hoisted(() => ({ value: { config: { features: { notifications_api: 1 } }, loaded: true } }))
vi.mock('../../hooks/useClientConfig', () => ({ useClientConfig: () => cfg.value }))
vi.mock('../../services/notificationsApi', () => ({ getNotificationSettings: vi.fn(), putNotificationSettings: vi.fn() }))
vi.mock('../../telemetry/client', () => ({ emit: vi.fn() }))

import * as api from '../../services/notificationsApi'
import { emit } from '../../telemetry/client'
import { initI18n } from '../../i18n'
import NotificationsSection from './NotificationsSection'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
const cat = (on = true) => ({ enabled: on })
const BASE = {
  categories: { price_drops: cat(), trip_reminders: cat(), morning_brief: cat(), weather: cat(), nearby: cat(), social: cat(), quiz: cat() },
  quiet_hours: { enabled: false, start: '22:00', end: '07:00' },
  daily_cap: 3, timezone: 'Asia/Kolkata', quiet_hours_active: false, push: { fcm: false, apns: false }, devices: 2,
}
let root; let host; let server
const q = (tid) => host.querySelector(`[data-tid="${tid}"]`)
const render = async () => { await act(async () => { root.render(<NotificationsSection />) }) }
const click = async (el) => { await act(async () => { el.dispatchEvent(new MouseEvent('click', { bubbles: true })) }) }
const setVal = async (el, v) => {
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(el, v)
    el.dispatchEvent(new Event('input', { bubbles: true }))
  })
}

beforeEach(async () => {
  await initI18n({ lng: 'en' })
  host = document.createElement('div'); document.body.appendChild(host); root = createRoot(host)
  vi.clearAllMocks()
  cfg.value = { config: { features: { notifications_api: 1 } }, loaded: true }
  server = JSON.parse(JSON.stringify(BASE))
  api.getNotificationSettings.mockImplementation(() => Promise.resolve(server))
  api.putNotificationSettings.mockImplementation((_t, patch) => {
    if (patch.categories) for (const [k, v] of Object.entries(patch.categories)) server.categories[k] = { ...server.categories[k], ...v }
    if (patch.quiet_hours) server.quiet_hours = patch.quiet_hours
    if (patch.daily_cap) server.daily_cap = patch.daily_cap
    return Promise.resolve(JSON.parse(JSON.stringify(server)))
  })
})
afterEach(() => { act(() => root.unmount()); host.remove() })

describe('NotificationsSection', () => {
  it('renders nothing without features.notifications_api and never fetches', async () => {
    cfg.value = { config: { features: {} }, loaded: true }
    await render()
    expect(host.innerHTML).toBe('')
    expect(api.getNotificationSettings).not.toHaveBeenCalled()
  })

  it('shows five categories (no social/quiz) and emits the view event', async () => {
    await render()
    expect(host.querySelectorAll('[data-tid^="notif.category."]').length).toBe(5)
    expect(q('notif.category.social')).toBeNull()
    expect(emit).toHaveBeenCalledWith('notif_settings_view', {})
    expect(q('notif.no_devices')).toBeNull()
  })

  it('toggles a category, saving and emitting', async () => {
    await render()
    await click(q('notif.category.weather'))
    expect(api.putNotificationSettings).toHaveBeenLastCalledWith('tok', { categories: { weather: { enabled: false } } })
    expect(q('notif.category.weather').getAttribute('aria-checked')).toBe('false')
    expect(emit).toHaveBeenCalledWith('notif_category_toggle', { category: 'weather', on: false })
  })

  it('reverts a toggle on error', async () => {
    api.putNotificationSettings.mockRejectedValue({ status: 422 })
    await render()
    await click(q('notif.category.nearby'))
    expect(q('notif.category.nearby').getAttribute('aria-checked')).toBe('true')
    expect(host.querySelector('[role="alert"]')).not.toBeNull()
    expect(emit).not.toHaveBeenCalledWith('notif_category_toggle', expect.anything())
  })

  it('edits quiet hours and shows the timezone', async () => {
    await render()
    await click(q('notif.quiet.toggle'))
    expect(api.putNotificationSettings).toHaveBeenLastCalledWith('tok', { quiet_hours: { enabled: true, start: '22:00', end: '07:00' } })
    expect(emit).toHaveBeenCalledWith('notif_quiet_hours_change', { enabled: true })
    expect(q('notif.quiet.timezone').textContent).toContain('Asia/Kolkata')
    await setVal(q('notif.quiet.start'), '23:30')
    expect(api.putNotificationSettings).toHaveBeenLastCalledWith('tok', { quiet_hours: { enabled: true, start: '23:30', end: '07:00' } })
  })

  it('notes a missing timezone', async () => {
    server.timezone = null
    server.quiet_hours.enabled = true
    await render()
    expect(q('notif.quiet.no_timezone')).not.toBeNull()
  })

  it('steps the daily cap within 1-10', async () => {
    await render()
    await click(q('notif.cap.inc'))
    expect(api.putNotificationSettings).toHaveBeenLastCalledWith('tok', { daily_cap: 4 })
    expect(q('notif.cap.value').textContent).toBe('4')
    expect(emit).toHaveBeenCalledWith('notif_cap_change', { cap: 4 })
  })

  it('disables the stepper at the ends', async () => {
    server.daily_cap = 10
    await render()
    expect(q('notif.cap.inc').disabled).toBe(true)
    expect(q('notif.cap.dec').disabled).toBe(false)
  })

  it('shows the no-devices note', async () => {
    server.devices = 0
    await render()
    expect(q('notif.no_devices')).not.toBeNull()
  })

  it('an earlier save answering first does not roll back a newer optimistic edit', async () => {
    await render()
    const rel = []
    for (let i = 0; i < 2; i += 1) {
      api.putNotificationSettings.mockImplementationOnce((_t, patch) => new Promise((res) => {
        rel.push(() => res({ ...JSON.parse(JSON.stringify(BASE)), ...(patch.daily_cap ? { daily_cap: patch.daily_cap } : {}) }))
      }))
    }
    await click(q('notif.quiet.toggle'))
    await click(q('notif.cap.inc'))
    expect(q('notif.cap.value').textContent).toBe('4')
    await act(async () => { rel[0]() })
    expect(q('notif.cap.value').textContent).toBe('4')
    await act(async () => { rel[1]() })
    expect(q('notif.cap.value').textContent).toBe('4')
  })
})
