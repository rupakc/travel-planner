// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'

const auth = { token: 'tok', user: { id: 5 } }
const v2 = { on: true, livePrices: true }
const changed = vi.fn()
vi.mock('../../context/AuthContext', () => ({ useOptionalAuth: () => auth }))
vi.mock('../../context/AlertsContext', () => ({ useAlerts: () => ({ watchesChanged: changed }) }))
vi.mock('../../hooks/useAlertsV2', () => ({ useAlertsV2: () => v2 }))
vi.mock('../../services/alertsApi', () => ({ getSuggestions: vi.fn(), quickWatch: vi.fn() }))
vi.mock('../../telemetry/client', () => ({ emit: vi.fn() }))

import * as alertsApi from '../../services/alertsApi'
import { emit } from '../../telemetry/client'
import WatchSuggestions from './WatchSuggestions'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
let root; let host
const LIST = {
  live_prices: true,
  suggestions: [
    { kind: 'flight', title: 'NYC to Tokyo', spec: { a: 1 }, reason: 'selected_in_plan', already_watching: false },
    { kind: 'hotel', title: 'Hotel Lux', spec: { b: 1 }, reason: 'selected_in_plan', already_watching: false },
    { kind: 'trip', title: 'Whole trip', spec: { c: 1 }, reason: 'trip_total', already_watching: false },
    { kind: 'activity', title: 'Tour', spec: { d: 1 }, reason: 'departure_soon', already_watching: true },
  ],
}
const render = async (props = { planId: 9 }) => {
  await act(async () => { root.render(<WatchSuggestions {...props} />) })
}
const q = (tid) => document.body.querySelector(`[data-tid="${tid}"]`)
const qa = (tid) => [...document.body.querySelectorAll(`[data-tid="${tid}"]`)]
const click = async (el) => { await act(async () => { el.dispatchEvent(new MouseEvent('click', { bubbles: true })) }) }

beforeEach(() => {
  host = document.createElement('div'); document.body.appendChild(host); root = createRoot(host)
  vi.clearAllMocks(); window.localStorage.clear(); v2.livePrices = true
  alertsApi.getSuggestions.mockResolvedValue(LIST)
})
afterEach(() => { act(() => root.unmount()); host.remove() })

describe('WatchSuggestions', () => {
  it('not shown without live prices', async () => {
    v2.livePrices = false
    await render()
    expect(alertsApi.getSuggestions).not.toHaveBeenCalled()
    expect(q('watch-suggest')).toBeNull()
  })

  it('not shown for an empty list', async () => {
    alertsApi.getSuggestions.mockResolvedValue({ suggestions: [], live_prices: true })
    await render()
    expect(q('watch-suggest')).toBeNull()
  })

  it('once per plan per user', async () => {
    await render()
    expect(q('watch-suggest')).not.toBeNull()
    expect(window.localStorage.getItem('tp_suggest_seen:5:9')).toBe('1')
    await click(q('watch-suggest-dismiss'))
    expect(q('watch-suggest')).toBeNull()
    act(() => root.unmount()) // remount: only localStorage can remember
    root = createRoot(host)
    await render({ planId: 9 })
    expect(alertsApi.getSuggestions).toHaveBeenCalledTimes(1)
    expect(q('watch-suggest')).toBeNull()
    await render({ planId: 10 }) // another plan is offered again
    expect(q('watch-suggest')).not.toBeNull()
  })

  it('pre-ticks all but trip and disables already-watched rows', async () => {
    await render()
    const boxes = qa('watch-suggest-toggle')
    expect(boxes.map((b) => b.checked)).toEqual([true, true, false, true])
    expect(boxes[3].disabled).toBe(true)
    expect(q('watch-suggest-accept').textContent).toContain('2')
  })

  it('watch N creates ticked only', async () => {
    alertsApi.quickWatch.mockResolvedValue({ watch: { id: 1 }, existing: false })
    await render()
    await click(q('watch-suggest-accept'))
    expect(alertsApi.quickWatch).toHaveBeenCalledTimes(2)
    expect(alertsApi.quickWatch.mock.calls.map((c) => c[1].kind)).toEqual(['flight', 'hotel'])
    expect(alertsApi.quickWatch.mock.calls[0][1]).toMatchObject({ surface: 'suggest', plan_id: 9 })
    expect(changed).toHaveBeenCalled()
    expect(q('watch-suggest-done')).not.toBeNull()
  })

  it('partial failure keeps the failed row with retry', async () => {
    alertsApi.quickWatch
      .mockResolvedValueOnce({ watch: { id: 1 }, existing: false })
      .mockRejectedValueOnce({ code: 'watch_limit', status: 409 })
    await render()
    await click(q('watch-suggest-accept'))
    expect(q('watch-suggest-done')).toBeNull()
    expect(qa('watch-suggest-retry')).toHaveLength(1)
    expect(document.body.querySelector('[role="alert"]')).not.toBeNull()
    alertsApi.quickWatch.mockResolvedValueOnce({ watch: { id: 2 }, existing: false })
    await click(q('watch-suggest-retry'))
    expect(alertsApi.quickWatch).toHaveBeenCalledTimes(3)
    expect(q('watch-suggest-done')).not.toBeNull()
  })

  it('force skips the once-per-plan guard but not live prices or empty', async () => {
    window.localStorage.setItem('tp_suggest_seen:5:9', '1')
    await render({ planId: 9, force: true })
    expect(q('watch-suggest')).not.toBeNull()
    act(() => root.unmount()); root = createRoot(host)
    v2.livePrices = false
    await render({ planId: 9, force: true })
    expect(q('watch-suggest')).toBeNull()
  })

  it('onDone fires on dismiss', async () => {
    const onDone = vi.fn()
    await render({ planId: 9, onDone })
    await click(q('watch-suggest-dismiss'))
    expect(onDone).toHaveBeenCalledTimes(1)
  })

  it('Escape dismisses', async () => {
    await render()
    await act(async () => { document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })) })
    expect(q('watch-suggest')).toBeNull()
    expect(emit).toHaveBeenCalledWith('alert_suggest', { action: 'dismissed', count: 4 })
  })

  it('telemetry shown, accepted and dismissed with count', async () => {
    alertsApi.quickWatch.mockResolvedValue({ watch: { id: 1 }, existing: false })
    await render()
    expect(emit).toHaveBeenCalledWith('alert_suggest', { action: 'shown', count: 4 })
    await click(q('watch-suggest-accept'))
    expect(emit).toHaveBeenCalledWith('alert_suggest', { action: 'accepted', count: 2 })
    expect(emit).not.toHaveBeenCalledWith('alert_suggest', expect.objectContaining({ action: 'dismissed' }))
    await click(q('watch-suggest-done'))
    expect(emit).not.toHaveBeenCalledWith('alert_suggest', expect.objectContaining({ action: 'dismissed' }))
    // dismiss path on a fresh plan
    await render({ planId: 11 })
    await click(q('watch-suggest-dismiss'))
    expect(emit).toHaveBeenCalledWith('alert_suggest', { action: 'dismissed', count: 4 })
  })
})
