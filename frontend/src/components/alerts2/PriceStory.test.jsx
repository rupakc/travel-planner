// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'

vi.mock('../../context/AuthContext', () => ({ useAuth: () => ({ token: 'tok' }) }))
vi.mock('../../services/alertsApi', () => ({ getStory: vi.fn(), requestAdvice: vi.fn() }))
vi.mock('../../services/api', () => ({ updateFareWatch: vi.fn(), updatePriceWatch: vi.fn() }))

import * as alertsApi from '../../services/alertsApi'
import * as api from '../../services/api'
import PriceStory from './PriceStory'
import TargetSlider from './TargetSlider'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const pt = (i, price) => ({ at: `2026-11-0${i + 1}T10:00:00Z`, price })
const STORY = {
  kind: 'flight', watch_id: 7, currency: 'USD', mode: 'any_drop', target: null,
  points: [pt(0, 500), pt(1, 470), pt(2, 430)], baseline: 500,
  latest: pt(2, 430), lowest: pt(2, 430), typical: { low: 390, high: 520, source: 'google' },
  verdict: 'typical', advice: { code: 'at_lowest', params: {} }, checked_days_ago: 2,
  pending_first_check: false, estimate: null, caught: null, live_prices: true,
}

let root; let host
const render = async (el) => { await act(async () => { root.render(el) }) }
const setRange = (el, v) => {
  const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set
  set.call(el, String(v)); el.dispatchEvent(new Event('input', { bubbles: true }))
}
const matchMedia = (reduced) => { window.matchMedia = () => ({ matches: reduced, addEventListener() {}, removeEventListener() {} }) }

beforeEach(() => {
  host = document.createElement('div'); document.body.appendChild(host); root = createRoot(host)
  matchMedia(false); vi.clearAllMocks()
  window.requestAnimationFrame = (f) => setTimeout(f, 0); window.cancelAnimationFrame = clearTimeout
})
afterEach(() => { act(() => root.unmount()); host.remove() })

describe('PriceStory', () => {
  it('renders paused advice without verdict when stale and no live prices', async () => {
    await render(<PriceStory story={{ ...STORY, verdict: null, live_prices: false, checked_days_ago: 9, advice: { code: 'checks_paused', params: { days: 9 } } }} />)
    expect(host.textContent).toContain('Live price checks are paused')
    expect(host.textContent).toContain('9 days ago')
    expect(host.querySelector('[data-testid="verdict-chip"]')).toBeNull()
  })

  it('shows verdict chip with text and the translated advice', async () => {
    await render(<PriceStory story={{ ...STORY, verdict: 'good' }} />)
    expect(host.querySelector('[data-testid="verdict-chip"]').textContent).toBe('Good price')
    expect(host.querySelector('[data-testid="advice"]').textContent).toBe('The lowest price seen so far.')
    expect(host.textContent).toContain('Checked 2 days ago')
  })

  it('labels an estimate', async () => {
    await render(<PriceStory story={{ ...STORY, estimate: { price: 400, source: 'estimate' } }} />)
    expect(host.querySelector('[data-testid="estimate"]').textContent).toContain('not an observed price')
  })

  it('keyboard scrub announces price', async () => {
    await render(<PriceStory story={STORY} />)
    const group = host.querySelector('[role="group"]')
    await act(async () => { group.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true })) })
    expect(host.querySelector('[data-testid="chart-live"]').textContent).toContain('$500.00')
    await act(async () => { group.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true })) })
    expect(host.querySelector('[data-testid="chart-live"]').textContent).toContain('$470.00')
    await act(async () => { group.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft', bubbles: true })) })
    expect(host.querySelector('[data-testid="chart-live"]').textContent).toContain('$500.00')
  })

  it('tip button only for flights', async () => {
    await render(<PriceStory story={STORY} />)
    expect(host.textContent).toContain('Get a timing tip')
    await render(<PriceStory story={{ ...STORY, kind: 'hotel' }} />)
    expect(host.textContent).not.toContain('Get a timing tip')
  })

  it('requests a tip for a flight', async () => {
    alertsApi.requestAdvice.mockResolvedValue({ tip: 'Book soon.', source: 'ai' })
    await render(<PriceStory story={STORY} />)
    const btn = [...host.querySelectorAll('button')].find((b) => b.textContent.includes('timing tip'))
    await act(async () => { btn.click() })
    expect(alertsApi.requestAdvice).toHaveBeenCalledWith('tok', 'flight', 7)
    expect(host.querySelector('[data-testid="tip"]').textContent).toContain('Book soon.')
  })

  it('reduced motion skips the draw-in', async () => {
    matchMedia(true)
    await render(<PriceStory story={STORY} />)
    expect(host.querySelector('path[data-draw]')).toBeNull()
    act(() => root.unmount()); root = createRoot(host)
    matchMedia(false)
    await render(<PriceStory story={STORY} />)
    expect(host.querySelector('path[data-draw="in"]')).not.toBeNull()
  })

  it('no chart with fewer than 2 points, shows few-checks copy', async () => {
    await render(<PriceStory story={{ ...STORY, points: [pt(0, 500)], advice: { code: 'few_checks', params: { n: 1 } } }} />)
    expect(host.querySelector('[data-testid="price-chart"]')).toBeNull()
    expect(host.querySelector('[data-testid="few-checks"]').textContent).toContain('1 check so far')
  })

  it('loads the story and commits a target through the right update call', async () => {
    alertsApi.getStory.mockResolvedValue({ ...STORY, kind: 'hotel' })
    api.updatePriceWatch.mockResolvedValue({})
    await render(<PriceStory kind="hotel" watchId={7} />)
    expect(alertsApi.getStory).toHaveBeenCalledWith('tok', 'hotel', 7)
    const input = host.querySelector('input[type="range"]')
    await act(async () => { setRange(input, 410); input.dispatchEvent(new Event('pointerup', { bubbles: true })) })
    expect(api.updatePriceWatch).toHaveBeenCalledWith(7, { target_price: 410, alert_mode: 'below_target' }, 'tok')
  })
})

describe('TargetSlider', () => {
  const points = [{ price: 500 }, { price: 470 }, { price: 430 }, { price: 450 }]
  it('slider commits target once on release', async () => {
    const onCommit = vi.fn()
    await render(<TargetSlider min={300} max={600} value={500} points={points} onCommit={onCommit} />)
    const input = host.querySelector('input')
    await act(async () => { setRange(input, 460) })
    await act(async () => { setRange(input, 440) })
    expect(onCommit).not.toHaveBeenCalled()
    expect(host.textContent).toContain('1 of your last 4 checks was at or below this.')
    await act(async () => { input.dispatchEvent(new Event('pointerup', { bubbles: true })) })
    await act(async () => { input.dispatchEvent(new Event('blur', { bubbles: false })) })
    expect(onCommit).toHaveBeenCalledTimes(1)
    expect(onCommit).toHaveBeenCalledWith(440)
  })
})
