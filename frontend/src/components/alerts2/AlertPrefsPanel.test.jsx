// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'

vi.mock('../../context/AuthContext', () => ({ useAuth: () => ({ token: 'tok' }) }))
vi.mock('../../services/alertsApi', () => ({ getAlertPrefs: vi.fn(), putAlertPrefs: vi.fn() }))
vi.mock('../../services/accountApi', () => ({ patchSettings: vi.fn() }))
vi.mock('../../telemetry/client', () => ({ emit: vi.fn() }))

import * as alertsApi from '../../services/alertsApi'
import * as accountApi from '../../services/accountApi'
import { emit } from '../../telemetry/client'
import AlertPrefsPanel from './AlertPrefsPanel'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
const BASE = {
  digest_weekly: false, digest_push: false, digest_day: 1, instant: 'all',
  quiet_hours: { enabled: false, start: '22:00', end: '07:00' },
  daily_cap: { flight: 3, hotel: 3, activity: 3, trip: 3 }, group_window_min: 15,
  timezone: 'Asia/Kolkata', quiet_hours_active: false,
}
let root; let host
const q = (tid) => host.querySelector(`[data-tid="${tid}"]`)
const render = async () => { await act(async () => { root.render(<AlertPrefsPanel />) }) }
const click = async (el) => { await act(async () => { el.dispatchEvent(new MouseEvent('click', { bubbles: true })) }) }
const setVal = async (el, v) => {
  const proto = el.tagName === 'SELECT' ? HTMLSelectElement.prototype : HTMLInputElement.prototype
  await act(async () => {
    Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, v)
    el.dispatchEvent(new Event(el.tagName === 'SELECT' ? 'change' : 'input', { bubbles: true }))
  })
}
let server = { ...BASE }
const echo = (patch) => { server = { ...server, ...patch }; return Promise.resolve(server) }

beforeEach(() => {
  host = document.createElement('div'); document.body.appendChild(host); root = createRoot(host)
  vi.clearAllMocks(); server = { ...BASE }
  alertsApi.getAlertPrefs.mockResolvedValue({ ...BASE })
  alertsApi.putAlertPrefs.mockImplementation((_t, patch) => echo(patch))
})
afterEach(() => { act(() => root.unmount()); host.remove(); vi.restoreAllMocks() })

describe('AlertPrefsPanel', () => {
  it('saves each field and rolls back on 422', async () => {
    await render()
    await click(q('alert-prefs-digest'))
    expect(alertsApi.putAlertPrefs).toHaveBeenLastCalledWith('tok', { digest_weekly: true })
    expect(q('alert-prefs-digest').getAttribute('aria-checked')).toBe('true')
    await setVal(q('alert-prefs-day'), '5')
    expect(alertsApi.putAlertPrefs).toHaveBeenLastCalledWith('tok', { digest_day: 5 })
    await click(q('alert-prefs-digest-push'))
    expect(alertsApi.putAlertPrefs).toHaveBeenLastCalledWith('tok', { digest_push: true })
    await click(q('alert-prefs-instant'))
    expect(alertsApi.putAlertPrefs).toHaveBeenLastCalledWith('tok', { instant: 'targets_only' })
    await click(q('alert-prefs-quiet'))
    expect(alertsApi.putAlertPrefs).toHaveBeenLastCalledWith('tok', { quiet_hours: { enabled: true, start: '22:00', end: '07:00' } })
    await setVal(q('alert-prefs-quiet-start'), '23:00')
    expect(alertsApi.putAlertPrefs).toHaveBeenLastCalledWith('tok', { quiet_hours: { enabled: true, start: '23:00', end: '07:00' } })
    await click(q('alert-prefs-cap-hotel-inc'))
    expect(alertsApi.putAlertPrefs).toHaveBeenLastCalledWith('tok', { daily_cap: { flight: 3, hotel: 4, activity: 3, trip: 3 } })
    await setVal(q('alert-prefs-group'), '60')
    expect(alertsApi.putAlertPrefs).toHaveBeenLastCalledWith('tok', { group_window_min: 60 })
    for (const call of alertsApi.putAlertPrefs.mock.calls) {
      expect(call[1]).not.toHaveProperty('timezone')
      expect(call[1]).not.toHaveProperty('quiet_hours_active')
    }

    alertsApi.putAlertPrefs.mockRejectedValueOnce({ status: 422, error_code: 'alert_prefs_invalid' })
    await click(q('alert-prefs-instant'))
    expect(q('alert-prefs-instant').getAttribute('aria-checked')).toBe('true')
    expect(q('alert-prefs-error')).not.toBeNull()
    alertsApi.putAlertPrefs.mockRejectedValueOnce({ status: 422 })
    await click(q('alert-prefs-cap-hotel-dec'))
    expect(q('alert-prefs-cap-hotel-value').textContent).toBe('4')
  })

  it('shows the digest push toggle only when the digest is on', async () => {
    await render()
    expect(q('alert-prefs-digest-push')).toBeNull()
    await click(q('alert-prefs-digest'))
    expect(q('alert-prefs-digest-push')).not.toBeNull()
  })

  it('offers browser timezone when missing', async () => {
    alertsApi.getAlertPrefs.mockResolvedValueOnce({ ...BASE, timezone: null, quiet_hours: { enabled: true, start: '22:00', end: '07:00' } })
    vi.spyOn(Intl, 'DateTimeFormat').mockImplementation(() => ({ resolvedOptions: () => ({ timeZone: 'Asia/Kolkata' }) }))
    accountApi.patchSettings.mockResolvedValue({})
    alertsApi.getAlertPrefs.mockResolvedValueOnce({ ...BASE, timezone: 'Asia/Kolkata', quiet_hours_active: true, quiet_hours: { enabled: true, start: '22:00', end: '07:00' } })
    await render()
    const btn = q('alert-prefs-use-timezone')
    expect(btn.textContent).toContain('Asia/Kolkata')
    await click(btn)
    expect(accountApi.patchSettings).toHaveBeenCalledWith('tok', { timezone: 'Asia/Kolkata' })
    expect(q('alert-prefs-use-timezone')).toBeNull()
    expect(q('alert-prefs-quiet-inactive')).toBeNull()
  })

  it('quiet hours inactive notice without timezone', async () => {
    alertsApi.getAlertPrefs.mockResolvedValueOnce({ ...BASE, timezone: null, quiet_hours: { enabled: true, start: '22:00', end: '07:00' } })
    await render()
    expect(q('alert-prefs-quiet-inactive')).not.toBeNull()
    act(() => root.unmount()); root = createRoot(host)
    alertsApi.getAlertPrefs.mockResolvedValueOnce({ ...BASE, quiet_hours: { enabled: false, start: '22:00', end: '07:00' }, timezone: null })
    await render()
    expect(q('alert-prefs-quiet-inactive')).toBeNull()
  })

  it('telemetry field enum only', async () => {
    await render()
    await click(q('alert-prefs-digest'))
    await click(q('alert-prefs-digest-push'))
    await click(q('alert-prefs-instant'))
    await click(q('alert-prefs-quiet'))
    await click(q('alert-prefs-cap-trip-dec'))
    await setVal(q('alert-prefs-group'), '30')
    const fields = emit.mock.calls.map((c) => { expect(c[0]).toBe('alert_prefs_change'); expect(Object.keys(c[1])).toEqual(['field']); return c[1].field })
    expect(fields).toEqual(['digest', 'digest', 'instant', 'quiet_hours', 'cap', 'group'])
  })

  it('keeps 44px targets and data-tids on controls', async () => {
    await render()
    for (const b of host.querySelectorAll('button, select, input')) expect(b.getAttribute('data-tid')).toBeTruthy()
    expect(host.querySelector('button').className).toContain('min-h-[44px]')
  })
})
