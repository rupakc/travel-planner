// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'

vi.mock('../../services/accountApi', () => ({ getQuota: vi.fn() }))
vi.mock('../../context/AuthContext', () => ({ useAuth: () => ({ token: 'tok' }) }))

import QuotaSection from './QuotaSection'
import { getQuota } from '../../services/accountApi'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

let container, root
const tid = (id) => container.querySelector(`[data-tid="${id}"]`)
const render = async (props) => act(async () => { root.render(<QuotaSection {...props} />) })

beforeEach(() => {
  vi.clearAllMocks()
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})
afterEach(() => { act(() => root.unmount()); container.remove() })

describe('QuotaSection', () => {
  it('renders used / limit bars and the reset time', async () => {
    getQuota.mockResolvedValue({
      day: '2026-11-11', resets_at: '2026-11-12T00:00:00Z',
      buckets: { search: { used: 3, limit: 20 }, chat: { used: 0, limit: null } },
    })
    await render({ account: {} })
    expect(tid('quota.count.search').textContent).toBe('3 / 20')
    expect(container.querySelector('[role="progressbar"]').getAttribute('aria-valuenow')).toBe('3')
    expect(tid('quota.count.chat').textContent).toBe('No daily limit')
    expect(tid('quota.resets').textContent).toMatch(/^Resets at .+/)
  })

  it('renders nothing without an account and does not call the API', async () => {
    await render({ account: null })
    expect(container.innerHTML).toBe('')
    expect(getQuota).not.toHaveBeenCalled()
  })

  it('hides on a 404', async () => {
    getQuota.mockRejectedValue({ status: 404 })
    await render({ account: {} })
    expect(container.innerHTML).toBe('')
  })
})
