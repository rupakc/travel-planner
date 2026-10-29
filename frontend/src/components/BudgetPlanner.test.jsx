// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import BudgetPlanner from './BudgetPlanner'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const allocation = { flights: 650, stay: 1050, activities: 450, other: 850 }
const fit = (over = {}) => ({
  hotels: { fits: new Set(), over: new Set(), count: 6, total: 12 },
  flights: { fits: new Set(), over: new Set(), count: 4, total: 9 },
  activities: { picked: new Set(['a', 'b', 'c', 'd', 'e']), spent: 212 },
  nights: 7,
  ...over,
})

// React listens for 'input' on range/number inputs; set the value natively first
const setValue = (el, value) => {
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(el, String(value))
  el.dispatchEvent(new Event('input', { bubbles: true }))
}

describe('BudgetPlanner', () => {
  let container, root
  beforeEach(() => {
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
  })
  afterEach(() => {
    act(() => root.unmount())
    container.remove()
    delete window.matchMedia
  })

  const props = (over = {}) => ({
    allocation,
    fit: fit(),
    onChange: () => {},
    onTotalChange: () => {},
    onReset: () => {},
    showOnlyFits: false,
    onShowOnlyFitsChange: () => {},
    onFindCheaperHotels: () => {},
    findingCheaperHotels: false,
    ...over,
  })
  const render = (over) => act(() => root.render(<BudgetPlanner {...props(over)} />))
  const text = () => container.textContent
  const slider = (key) => container.querySelector(`input[type="range"][data-key="${key}"]`)
  const button = (t) => [...container.querySelectorAll('button')].find((b) => b.textContent.includes(t))
  const totalInput = () => container.querySelector('input[type="number"]')

  it('shows the total, three labelled sliders and the read-only rest', () => {
    render()
    expect(text()).toContain('Budget planner')
    expect(totalInput().value).toBe('3000')
    for (const [key, label] of [['flights', 'flights'], ['stay', 'stay'], ['activities', 'activities']]) {
      const s = slider(key)
      expect(s.step).toBe('10')
      expect(s.min).toBe('0')
      expect(s.max).toBe('3000')
      expect(s.getAttribute('aria-valuetext')).toBe(`$${allocation[key].toLocaleString()} for ${label}`)
      expect(container.querySelector(`label[for="${s.id}"]`)).not.toBeNull()
    }
    expect(slider('stay').getAttribute('aria-valuetext')).toBe('$1,050 for stay')
    expect(text()).toContain('Everything else')
    expect(text()).toContain('food, transport, extras')
    expect(text()).toContain('$850')
    expect(text()).toContain('per person')
    expect(slider('other')).toBeNull()
  })

  it('draws a stacked bar in the CostBreakdown colours', () => {
    render()
    const bar = container.querySelector('[role="img"]')
    expect(bar.getAttribute('aria-label')).toBe('Flights $650, Stay $1,050, Activities $450, Everything else $850')
    const segs = [...bar.children]
    expect(segs.map((s) => s.className.match(/bg-\w+-\d+/)[0])).toEqual(['bg-sky-500', 'bg-purple-500', 'bg-green-500', 'bg-gray-300'])
    expect(segs[1].style.width).toBe('35%')
  })

  it('shows what fits under each slider', () => {
    render()
    expect(text()).toContain('6 of 12 hotels fit')
    expect(text()).toContain('4 of 9 flights fit')
    expect(text()).toContain('Fits 5 activities ($212)')
    render({ fit: fit({ hotels: { fits: new Set(), over: new Set(), count: 1, total: 1 }, activities: { picked: new Set(['a']), spent: 0 } }) })
    expect(text()).toContain('1 of 1 hotel fits')
    expect(text()).toContain('Fits 1 activity ($0)')
  })

  it('reports slider moves and announces the result politely once the slider settles', () => {
    vi.useFakeTimers()
    try {
      const live = () => container.querySelector('[aria-live="polite"]').textContent
      const onChange = vi.fn()
      render({ onChange })
      expect(live()).toBe('')
      act(() => setValue(slider('stay'), 1200))
      expect(onChange).toHaveBeenCalledWith('stay', 1200)
      render({ onChange, allocation: { ...allocation, stay: 1200, other: 700 }, fit: fit({ hotels: { fits: new Set(), over: new Set(), count: 5, total: 12 } }) })
      act(() => vi.advanceTimersByTime(300))
      expect(live()).toBe('')
      // another tick restarts the wait
      act(() => setValue(slider('stay'), 1210))
      act(() => vi.advanceTimersByTime(300))
      expect(live()).toBe('')
      act(() => vi.advanceTimersByTime(200))
      expect(live()).toBe('Stay budget $1,200 — 5 of 12 hotels fit')
      // new props alone don't re-announce
      render({ onChange, allocation: { ...allocation, stay: 1300, other: 600 } })
      expect(live()).toBe('Stay budget $1,200 — 5 of 12 hotels fit')
      act(() => setValue(slider('activities'), 300))
      expect(onChange).toHaveBeenLastCalledWith('activities', 300)
      act(() => vi.advanceTimersByTime(500))
      expect(live()).toBe('Activities budget $450 — fits 5 activities ($212)')
    } finally {
      vi.useRealTimers()
    }
  })

  it('announces Reset and a total edit right away', () => {
    const live = () => container.querySelector('[aria-live="polite"]').textContent
    render()
    act(() => button('Reset').click())
    expect(live()).toBe('Budget split reset to the suggested shares')
    act(() => setValue(totalInput(), 3500))
    act(() => totalInput().dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })))
    render({ allocation: { ...allocation, other: 1350 } })
    expect(live()).toBe('Total budget $3,500')
  })

  it('points aria-controls at the body only while it is rendered', () => {
    render()
    const toggle = container.querySelector('button[aria-expanded]')
    expect(toggle.getAttribute('aria-controls')).toBe('budget-planner-body')
    expect(container.querySelector('#budget-planner-body')).not.toBeNull()
    act(() => toggle.click())
    expect(toggle.hasAttribute('aria-controls')).toBe(false)
  })

  it('commits an edited total on blur or Enter, ignoring junk', () => {
    const onTotalChange = vi.fn()
    render({ onTotalChange })
    act(() => setValue(totalInput(), 35))
    expect(onTotalChange).not.toHaveBeenCalled()
    act(() => setValue(totalInput(), 3500))
    act(() => totalInput().dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })))
    expect(onTotalChange).toHaveBeenCalledWith(3500)
    act(() => setValue(totalInput(), ''))
    act(() => totalInput().dispatchEvent(new FocusEvent('focusout', { bubbles: true })))
    expect(onTotalChange).toHaveBeenCalledTimes(1)
    expect(totalInput().value).toBe('3000')
  })

  it('toggles "Show only what fits"', () => {
    const onShowOnlyFitsChange = vi.fn()
    render({ onShowOnlyFitsChange })
    const sw = container.querySelector('[role="switch"]')
    expect(sw.textContent).toContain('Show only what fits')
    expect(sw.getAttribute('aria-checked')).toBe('false')
    act(() => sw.click())
    expect(onShowOnlyFitsChange).toHaveBeenCalledWith(true)
    render({ onShowOnlyFitsChange, showOnlyFits: true })
    expect(container.querySelector('[role="switch"]').getAttribute('aria-checked')).toBe('true')
  })

  it('offers cheaper hotels only when fewer than 3 fit, at stay ÷ nights', () => {
    const onFindCheaperHotels = vi.fn()
    render({ onFindCheaperHotels })
    expect(button('Find cheaper hotels')).toBeUndefined()
    render({ onFindCheaperHotels, fit: fit({ hotels: { fits: new Set(), over: new Set(), count: 2, total: 12 } }) })
    act(() => button('Find cheaper hotels').click())
    expect(onFindCheaperHotels).toHaveBeenCalledWith(150)
    render({ onFindCheaperHotels, findingCheaperHotels: true, fit: fit({ hotels: { fits: new Set(), over: new Set(), count: 0, total: 12 } }) })
    expect(button('Finding cheaper hotels').disabled).toBe(true)
  })

  it('does not offer cheaper hotels when the stay share is under $1 a night', () => {
    render({ allocation: { ...allocation, stay: 5, other: 1895 }, fit: fit({ hotels: { fits: new Set(), over: new Set(), count: 0, total: 12 } }) })
    expect(button('Find cheaper hotels')).toBeUndefined()
  })

  it('Reset calls onReset', () => {
    const onReset = vi.fn()
    render({ onReset })
    act(() => button('Reset').click())
    expect(onReset).toHaveBeenCalledTimes(1)
  })

  it('is expanded by default and collapses from its header', () => {
    render()
    const toggle = container.querySelector('button[aria-expanded]')
    expect(toggle.getAttribute('aria-expanded')).toBe('true')
    act(() => toggle.click())
    expect(toggle.getAttribute('aria-expanded')).toBe('false')
    expect(slider('stay')).toBeNull()
    expect(text()).toContain('Budget planner')
  })

  it('starts collapsed below 640px', () => {
    window.matchMedia = vi.fn((q) => ({ matches: q === '(max-width: 639px)', media: q }))
    render()
    expect(container.querySelector('button[aria-expanded]').getAttribute('aria-expanded')).toBe('false')
    expect(window.matchMedia).toHaveBeenCalledTimes(1)
  })
})
