// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'

const cfg = vi.hoisted(() => ({ value: { config: { features: { sharing: 1 } }, loaded: true } }))
vi.mock('../../hooks/useClientConfig', async (orig) => ({ ...(await orig()), useClientConfig: () => cfg.value }))
vi.mock('../../context/AuthContext', () => ({ useAuth: () => ({ token: 'tok' }) }))
vi.mock('../../services/api', () => ({ listShares: vi.fn(), revokeShare: vi.fn() }))

import { initI18n } from '../../i18n/index'
import { listShares, revokeShare } from '../../services/api'
import MyShares from './MyShares'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
let container, root
const SHARES = [
  { token: 'tok-aaaaaaaa', kind: 'plan', title: '<img src=x onerror=alert(1)> Lisbon', url: 'https://x.test/share/tok-aaaaaaaa', created_at: '2026-11-01T10:00:00Z' },
  { token: 'tok-bbbbbbbb', kind: 'savings', title: 'Price alerts', url: 'https://x.test/share/tok-bbbbbbbb', created_at: '2026-11-02T10:00:00Z' },
]
beforeEach(async () => {
  cfg.value = { config: { features: { sharing: 1 } }, loaded: true }
  await initI18n({ lng: 'en' })
  listShares.mockReset(); revokeShare.mockReset()
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container)
})
afterEach(() => { act(() => root.unmount()); container.remove(); vi.restoreAllMocks() })
const q = (id) => container.querySelector(`[data-tid="${id}"]`)
const qa = (id) => [...container.querySelectorAll(`[data-tid="${id}"]`)]
const mount = () => act(async () => root.render(<MyShares />))

describe('MyShares', () => {
  it('renders nothing and does not call the API when sharing is off', async () => {
    cfg.value = { config: { features: {} }, loaded: true }
    await mount()
    expect(container.innerHTML).toBe('')
    expect(listShares).not.toHaveBeenCalled()
  })

  it('hides silently on a 404 (old backend)', async () => {
    listShares.mockRejectedValue({ status: 404 })
    await mount()
    expect(container.innerHTML).toBe('')
  })

  it('shows the empty state', async () => {
    listShares.mockResolvedValue({ shares: [] })
    await mount()
    expect(q('shares.empty')).toBeTruthy()
  })

  it('lists shares and renders hostile titles as text', async () => {
    listShares.mockResolvedValue({ shares: SHARES })
    await mount()
    expect(qa('shares.item')).toHaveLength(2)
    expect(container.querySelector('img')).toBeNull()
    expect(qa('shares.item')[0].textContent).toContain('<img src=x onerror=alert(1)> Lisbon')
  })

  it('copies the link', async () => {
    listShares.mockResolvedValue({ shares: SHARES })
    const writeText = vi.fn().mockResolvedValue()
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    await mount()
    await act(async () => { qa('shares.copy')[0].click() })
    expect(writeText).toHaveBeenCalledWith('https://x.test/share/tok-aaaaaaaa')
    expect(container.querySelector('[role="status"]').textContent).toBe('Link copied')
  })

  it('revokes only after confirmation, and can be cancelled', async () => {
    listShares.mockResolvedValue({ shares: SHARES })
    revokeShare.mockResolvedValue()
    await mount()
    await act(async () => { qa('shares.revoke')[0].click() })
    expect(revokeShare).not.toHaveBeenCalled()
    await act(async () => { q('shares.revoke.no').click() })
    expect(q('shares.revoke.yes')).toBeNull()
    await act(async () => { qa('shares.revoke')[0].click() })
    await act(async () => { q('shares.revoke.yes').click() })
    expect(revokeShare).toHaveBeenCalledWith('tok', 'tok-aaaaaaaa')
    expect(qa('shares.item')).toHaveLength(1)
  })

  it('keeps the row and shows an error when revoke fails', async () => {
    listShares.mockResolvedValue({ shares: SHARES })
    revokeShare.mockRejectedValue(new Error('x'))
    await mount()
    await act(async () => { qa('shares.revoke')[0].click() })
    await act(async () => { q('shares.revoke.yes').click() })
    expect(qa('shares.item')).toHaveLength(2)
    expect(container.querySelector('[role="alert"]').textContent).toBe('Could not remove the link.')
  })
})
