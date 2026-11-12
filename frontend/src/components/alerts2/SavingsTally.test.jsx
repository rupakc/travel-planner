// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'

vi.mock('../../context/AuthContext', () => ({ useAuth: () => ({ token: 'tok' }) }))
vi.mock('../../services/alertsApi', () => ({ getSavings: vi.fn() }))

import SavingsTally from './SavingsTally'
import SavingsShareCard from './SavingsShareCard'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const SAV = {
  total_usd: 245, by_currency: { EUR: 12 }, drops_caught: 4, targets_hit: 1, watches_active: 6,
  best: { kind: 'hotel', watch_id: 3, title: 'Hotel Sol', caught: 120, currency: 'USD' },
  milestones: [50, 200, 1000], next_milestone: 1000, progress_pct: 24, since: '2026-11-01T00:00:00Z',
}
let root; let host
const render = async (el) => { await act(async () => { root.render(el) }) }
const matchMedia = (reduced) => { window.matchMedia = (q) => ({ matches: reduced && q.includes('reduced'), addEventListener() {}, removeEventListener() {} }) }

beforeEach(() => {
  host = document.createElement('div'); document.body.appendChild(host); root = createRoot(host)
  matchMedia(true)
  HTMLCanvasElement.prototype.getContext = () => ({ fillText() {}, fillRect() {}, measureText: () => ({ width: 10 }) })
})
afterEach(() => { act(() => root.unmount()); host.remove(); vi.restoreAllMocks() })

describe('SavingsTally', () => {
  it('ring progress matches progress_pct', async () => {
    await render(<SavingsTally savings={SAV} />)
    const ring = host.querySelector('[data-testid="savings-ring"]')
    expect(ring.getAttribute('data-progress')).toBe('24')
    const arc = ring.querySelectorAll('circle')[1]
    const circ = Number(arc.getAttribute('stroke-dasharray'))
    expect(Number(arc.getAttribute('stroke-dashoffset'))).toBeCloseTo(circ * 0.76, 3)
    expect(host.querySelectorAll('[data-testid="milestone-tick"]')).toHaveLength(3)
  })

  it('shows the eur chip separate from the usd total', async () => {
    await render(<SavingsTally savings={SAV} />)
    expect(host.querySelector('[data-testid="savings-total"]').textContent).toContain('$245')
    expect(host.querySelector('[data-testid="savings-total"]').textContent).not.toContain('€')
    expect(host.querySelector('[data-testid="savings-chips"]').textContent).toContain('€12')
    expect(host.textContent).toContain('Best catch: Hotel Sol')
    expect(host.textContent).not.toMatch(/\bsaved\b/i)
  })

  it('shows the empty state', async () => {
    await render(<SavingsTally savings={{ total_usd: 0, by_currency: {}, drops_caught: 0 }} />)
    expect(host.textContent).toContain('Your first drop will show here')
    expect(host.querySelector('[data-testid="savings-ring"]')).toBeNull()
  })

  it('has no count-up under reduced motion', async () => {
    await render(<SavingsTally savings={SAV} />)
    expect(host.querySelector('[data-testid="savings-total"]').textContent).toBe('Drops caught: $245.00')
  })

  it('renders one compact line', async () => {
    await render(<SavingsTally savings={SAV} compact />)
    expect(host.querySelector('[data-testid="savings-compact"]').textContent).toContain('Drops caught: $245')
  })
})

describe('SavingsShareCard', () => {
  it('closes on Escape without reaching a parent listener', async () => {
    const onClose = vi.fn(); const parent = vi.fn()
    document.addEventListener('keydown', parent)
    await render(<SavingsShareCard savings={{ total_usd: 57, by_currency: {}, drops_caught: 1 }} onClose={onClose} />)
    await act(async () => { document.activeElement.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })) })
    document.removeEventListener('keydown', parent)
    expect(onClose).toHaveBeenCalledTimes(1)
    expect(parent).not.toHaveBeenCalled()
  })
})
