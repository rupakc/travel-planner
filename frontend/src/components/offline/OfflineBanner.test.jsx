import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'

const journey = vi.hoisted(() => ({ enabled: true }))
const auth = vi.hoisted(() => ({ value: { user: { id: 7 }, offline: false } }))
vi.mock('../../hooks/useJourney', () => ({ useJourney: () => ({ enabled: journey.enabled }) }))
vi.mock('../../context/AuthContext', () => ({ useAuth: () => auth.value }))

import OfflineBanner from './OfflineBanner'
import { enqueue } from '../../offline/outbox'
import { _resetForTests } from '../../offline/idb'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

let el, root
async function render() {
  el = document.createElement('div')
  root = createRoot(el)
  await act(async () => { root.render(<OfflineBanner />) })
  await act(async () => { await new Promise((r) => setTimeout(r, 0)) })
}
const setOnLine = (v) => Object.defineProperty(navigator, 'onLine', { value: v, configurable: true })

beforeEach(() => { _resetForTests(); journey.enabled = true; auth.value = { user: { id: 7 }, offline: false }; setOnLine(true) })
afterEach(() => { act(() => root.unmount()); setOnLine(true) })

describe('OfflineBanner', () => {
  it('is hidden online', async () => {
    await render()
    expect(el.textContent).toBe('')
  })

  it('shows the offline line and the waiting count', async () => {
    await enqueue(7, { method: 'POST', path: '/trips/1/journal', body: {}, key: 'a' })
    await enqueue(7, { method: 'POST', path: '/trips/1/journal', body: {}, key: 'b' })
    setOnLine(false)
    await render()
    expect(el.textContent).toContain("You're offline. Saved trips still work.")
    expect(el.querySelector('[data-tid="offline-banner.pending"]').textContent).toBe('2 changes waiting to sync')
  })

  it('shows when the session could not be checked (auth offline)', async () => {
    auth.value = { user: { id: 7 }, offline: true }
    await render()
    expect(el.querySelector('[data-tid="offline-banner"]')).not.toBeNull()
    expect(el.querySelector('[data-tid="offline-banner.pending"]')).toBeNull()
  })

  it('never shows in the classic shell', async () => {
    journey.enabled = false
    setOnLine(false)
    await render()
    expect(el.textContent).toBe('')
  })
})
