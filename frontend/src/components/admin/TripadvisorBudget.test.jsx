// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'

const getTripadvisorBudget = vi.fn()
vi.mock('../../services/api', () => ({
  getTripadvisorBudget: (...a) => getTripadvisorBudget(...a),
}))

import TripadvisorBudget from './TripadvisorBudget'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

describe('TripadvisorBudget', () => {
  let container, root
  const render = async () => {
    await act(async () => { root.render(<TripadvisorBudget token="tok" />) })
  }

  beforeEach(() => {
    getTripadvisorBudget.mockReset()
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
  })
  afterEach(() => {
    act(() => root.unmount())
    container.remove()
  })

  it('shows used / cap', async () => {
    getTripadvisorBudget.mockResolvedValue({ enabled: true, configured: true, used: 120, cap: 1000, warn_at: 800, paused: false })
    await render()
    expect(container.textContent).toContain('120 of 1,000 billable entities used')
    expect(container.textContent).not.toContain('Paused')
  })

  it('warns from 80 % and explains the pause at the cap', async () => {
    getTripadvisorBudget.mockResolvedValue({ enabled: true, configured: true, used: 1000, cap: 1000, warn_at: 800, paused: true })
    await render()
    expect(container.textContent).toContain('Paused at the cap')
    expect(container.textContent).toContain('TRIPADVISOR_BUDGET_CAP')
  })

  it('is hidden on an older backend (404)', async () => {
    getTripadvisorBudget.mockRejectedValue(Object.assign(new Error('nf'), { response: { status: 404 } }))
    await render()
    expect(container.innerHTML).toBe('')
  })
})
