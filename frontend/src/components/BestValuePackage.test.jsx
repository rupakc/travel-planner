// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import BestValuePackage from './BestValuePackage'
import { buildBestValuePackage, applyPackage } from '../utils/bestValuePackage'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const searchData = { departure_date: '2026-04-01', return_date: '2026-04-10', budget_usd: 5000 }
const results = {
  flights: {
    results: [
      {
        airline: 'TestAir', flight_number: 'TA1', price_usd: 1234, source: 'live',
        booking_url: 'https://air.example/book',
        outbound: { airline: 'TestAir', flight_number: 'TA1', stops: 0, duration_minutes: 600 },
        return: { stops: 0, duration_minutes: 600 },
      },
    ],
  },
  hotels: {
    results: [
      { name: 'Hotel A', star_rating: 3, price_per_night_usd: 100, review_score: 8, booking_url: 'javascript:alert(1)' },
    ],
  },
  activities: { results: [{ name: 'Free Museum', price_usd: 0, similarity_score: 0.9, city: 'Paris', booking_url: 'https://a.example' }] },
  walking_tours: {
    results: [{ name: 'Old Town Tour', url: 'https://t.example/1', price_note: 'Free · tip-based', rating: 4.5, city: 'Paris' }],
  },
  sim: { plans: [{ provider: 'Airalo', plan_name: 'Europe 10GB', price_usd: 12, validity_days: 30, url: 'https://sim.example' }] },
}
const pkg = buildBestValuePackage(results, searchData)

describe('BestValuePackage', () => {
  let container, root
  const render = (props) => act(() => root.render(
    <BestValuePackage pkg={pkg} selections={{}} onApply={() => {}} onUndo={() => {}} canUndo={false} disabledReason={null} {...props} />,
  ))
  const button = (text) => [...container.querySelectorAll('button')].find((b) => b.textContent.includes(text))

  beforeEach(() => {
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
  })
  afterEach(() => {
    act(() => root.unmount())
    container.remove()
  })

  it('renders nothing for a null package', () => {
    render({ pkg: null })
    expect(container.innerHTML).toBe('')
  })

  it('renders one row per item with name and reason', () => {
    render()
    const rows = container.querySelectorAll('li')
    expect(rows).toHaveLength(pkg.items.length)
    const text = container.textContent
    expect(text).toContain('TestAir TA1')
    expect(text).toContain('Hotel A')
    expect(text).toContain('Free Museum')
    expect(text).toContain('Old Town Tour')
    expect(text).toContain('Airalo Europe 10GB')
    pkg.items.forEach((i) => expect(text).toContain(i.reason))
    expect(text).toContain('$1,234')
    expect(text).toContain('/night')
    expect(text).toContain('Free')
  })

  it('shows the total, budget chip and per-person flight note', () => {
    render()
    expect(container.textContent).toContain(`$${pkg.total.toLocaleString(undefined, { maximumFractionDigits: 0 })}`)
    expect(container.textContent).toContain(pkg.budget.label)
    expect(container.textContent).toContain('Flight prices are per person')
  })

  it('omits the flight note when there is no flight', () => {
    const noFlight = buildBestValuePackage({ hotels: results.hotels }, searchData)
    render({ pkg: noFlight })
    expect(container.textContent).not.toContain('Flight prices are per person')
  })

  it('calls onApply once on click', () => {
    const onApply = vi.fn()
    render({ onApply })
    act(() => button('Add all to My Plan').click())
    expect(onApply).toHaveBeenCalledTimes(1)
  })

  it('shows applied state with Undo', () => {
    const onUndo = vi.fn()
    render({ selections: applyPackage({}, pkg), canUndo: true, onUndo })
    const btn = button('Added to My Plan')
    expect(btn.disabled).toBe(true)
    act(() => button('Undo').click())
    expect(onUndo).toHaveBeenCalledTimes(1)
  })

  it('hides Undo when canUndo is false', () => {
    render({ selections: applyPackage({}, pkg), canUndo: false })
    expect(button('Undo')).toBeUndefined()
  })

  it('warns about replaced picks', () => {
    render({ selections: { hotel: { name: 'Other Hotel' } } })
    expect(container.textContent).toContain('Replaces your current hotel.')
  })

  it('joins conflict labels naturally', () => {
    render({ selections: { hotel: { name: 'Other' }, sim: { provider: 'X', plan_name: 'Y' } } })
    expect(container.textContent).toContain('Replaces your current hotel and SIM.')
    render({
      selections: {
        flight: { price_usd: 1, airline: 'Z' },
        hotel: { name: 'Other' },
        sim: { provider: 'X', plan_name: 'Y' },
      },
    })
    expect(container.textContent).toContain('Replaces your current flight, hotel and SIM.')
  })

  it('disables apply and shows the reason', () => {
    const onApply = vi.fn()
    render({ disabledReason: 'Close the open plan first', onApply })
    const btn = button('Add all to My Plan')
    expect(btn.disabled).toBe(true)
    expect(container.textContent).toContain('Close the open plan first')
    act(() => btn.click())
    expect(onApply).not.toHaveBeenCalled()
  })

  it('links through safeUrl', () => {
    render()
    const link = (name) => [...container.querySelectorAll('a, span')].find((e) => e.textContent === name)
    expect(link('Old Town Tour').getAttribute('href')).toBe('https://t.example/1')
    expect(link('TestAir TA1').getAttribute('href')).toBe('https://air.example/book')
    const hotelEl = link('Hotel A')
    expect(hotelEl.tagName).toBe('SPAN')
    expect(hotelEl.getAttribute('href')).toBeNull()
    expect(container.innerHTML).not.toContain('javascript:')
  })

  it('labels the package total and shows My Plan total only when it differs', () => {
    render({ searchData })
    expect(container.textContent).toContain('Package total')
    expect(container.textContent).not.toContain('My Plan total')
    const sel = applyPackage({}, pkg)
    render({ searchData, selections: sel })
    expect(container.textContent).not.toContain('My Plan total')
    render({ searchData, selections: { ...sel, activities: [...sel.activities, { name: 'Extra', price_usd: 500 }] } })
    expect(container.textContent).toContain('My Plan total: $')
  })

  it('keeps the live region mounted', () => {
    render()
    const live = container.querySelector('[aria-live]')
    expect(live).not.toBeNull()
    expect(live.className).not.toContain('empty:hidden')
  })
})
