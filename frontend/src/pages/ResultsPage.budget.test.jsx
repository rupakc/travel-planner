// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { HotelsSection, FlightsSection, ActivitiesSection } from './ResultsPage'
import { flightKey } from '../utils/budgetPlanner'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const DIM = 'opacity-60'
const hotel = (name, nightly) => ({ name, price_per_night_usd: nightly, location: 'Centre', star_rating: 3 })
const rt = (n, price) => ({
  price_usd: price,
  outbound: { airline: 'Air', flight_number: n, stops: 0, duration_minutes: 600 },
  return: { airline: 'Air', flight_number: `${n}r`, stops: 0, duration_minutes: 600 },
})
const legacy = (n, price) => ({ airline: `Air${n}`, flight_number: n, price_usd: price, stops: 0 })
const leg = (n, price, li) => ({ leg_index: li, price_usd: price, outbound: { airline: 'Air', flight_number: n, stops: 0 } })
const emptySel = { flight: null, flights: [], hotel: null, activities: [], places_to_see: [] }

describe('budget planner on result cards', () => {
  let container, root
  beforeEach(() => {
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
  })
  afterEach(() => {
    act(() => root.unmount())
    container.remove()
  })
  const render = (el) => act(() => root.render(el))
  const text = () => container.textContent
  const cardOf = (label) => [...container.querySelectorAll('.rounded-xl, tr')].find((c) => c.textContent.includes(label) && !c.querySelector('.rounded-xl'))
  const button = (t) => [...container.querySelectorAll('button')].find((b) => b.textContent.includes(t))
  // The card's content is dimmed; the over-budget tag itself stays at full opacity
  const isDimmed = (card) => card.className.includes(DIM) || !!card.querySelector(`.${DIM}`)
  const tagOf = (card) => [...card.querySelectorAll('span')].find((el) => /^Over your \w+ budget$/.test(el.textContent))
  const expectFullOpacityTag = (card) => {
    const tag = tagOf(card)
    expect(tag).toBeDefined()
    expect(tag.closest(`.${DIM}`)).toBeNull()
  }

  describe('HotelsSection', () => {
    const data = { results: [hotel('Fits Inn', 100), hotel('Pricey Palace', 400), hotel('Mystery Lodge', 'varies')] }
    const over = new Set(['Pricey Palace'])

    it('renders as before without a budget', () => {
      render(<HotelsSection data={data} selections={emptySel} onSelect={() => {}} />)
      expect(text()).not.toContain('Over your stay budget')
      expect(container.innerHTML).not.toContain(DIM)
    })

    it('dims and tags over-budget hotels but keeps them selectable; unknown prices untouched', () => {
      const onSelect = vi.fn()
      render(<HotelsSection data={data} selections={emptySel} onSelect={onSelect} budget={{ over, hideOver: false, onShowAll: () => {} }} />)
      expect(isDimmed(cardOf('Pricey Palace'))).toBe(true)
      expect(cardOf('Pricey Palace').textContent).toContain('Over your stay budget')
      expectFullOpacityTag(cardOf('Pricey Palace'))
      expect(cardOf('Pricey Palace').textContent).toContain('Add to Plan')
      expect(isDimmed(cardOf('Fits Inn'))).toBe(false)
      expect(isDimmed(cardOf('Mystery Lodge'))).toBe(false)
      expect((text().match(/Over your stay budget/g) || []).length).toBe(1)
      act(() => cardOf('Pricey Palace').querySelector('button').click())
      expect(onSelect).toHaveBeenCalledWith('hotel', data.results[1])
    })

    it('a selected over-budget hotel is tagged but not dimmed', () => {
      render(<HotelsSection data={data} selections={{ ...emptySel, hotel: data.results[1] }} onSelect={() => {}} budget={{ over, hideOver: false }} />)
      expect(isDimmed(cardOf('Pricey Palace'))).toBe(false)
      expect(cardOf('Pricey Palace').textContent).toContain('Added to Plan')
    })

    it('hides over-budget hotels with a "show all" row, except a selected one', () => {
      const onShowAll = vi.fn()
      render(<HotelsSection data={data} selections={emptySel} onSelect={() => {}} budget={{ over, hideOver: true, onShowAll }} />)
      expect(text()).not.toContain('Pricey Palace')
      expect(text()).toContain('Mystery Lodge')
      act(() => button('1 hidden — show all').click())
      expect(onShowAll).toHaveBeenCalledTimes(1)
      render(<HotelsSection data={data} selections={{ ...emptySel, hotel: data.results[1] }} onSelect={() => {}} budget={{ over, hideOver: true, onShowAll }} />)
      expect(text()).toContain('Pricey Palace')
      expect(button('hidden — show all')).toBeUndefined()
    })
  })

  describe('FlightsSection', () => {
    it('round-trip cards: dims, tags and hides by flight identity', () => {
      const cheap = rt('C1', 300)
      const dear = rt('D1', 900)
      const data = { results: [cheap, dear] }
      const over = new Set([flightKey(dear)])
      render(<FlightsSection data={data} selections={emptySel} onSelect={() => {}} budget={{ over, hideOver: false }} />)
      expect(isDimmed(cardOf('$900'))).toBe(true)
      expect(cardOf('$900').textContent).toContain('Over your flight budget')
      expectFullOpacityTag(cardOf('$900'))
      expect(isDimmed(cardOf('$300'))).toBe(false)
      render(<FlightsSection data={data} selections={emptySel} onSelect={() => {}} budget={{ over, hideOver: true }} />)
      expect(text()).not.toContain('$900')
      expect(text()).toContain('1 hidden — show all')
    })

    it('legacy table rows: dimmed and hidden too', () => {
      const a = legacy('A', 200)
      const b = legacy('B', 800)
      const over = new Set([flightKey(b)])
      render(<FlightsSection data={{ results: [a, b] }} selections={emptySel} onSelect={() => {}} budget={{ over, hideOver: false }} />)
      const row = [...container.querySelectorAll('tbody tr')].find((r) => r.textContent.includes('AirB'))
      expect(isDimmed(row)).toBe(true)
      expect(row.textContent).toContain('Over your flight budget')
      expectFullOpacityTag(row)
      render(<FlightsSection data={{ results: [a, b] }} selections={emptySel} onSelect={() => {}} budget={{ over, hideOver: true }} />)
      expect(container.querySelectorAll('tbody tr')).toHaveLength(1)
      expect(text()).toContain('1 hidden — show all')
    })

    it('multi-city: per-leg hiding keeps selected fares and the Add state', () => {
      const a0 = leg('A0', 100, 0)
      const b0 = leg('B0', 500, 0)
      const a1 = leg('A1', 900, 1)
      const data = { legs: [{ leg_index: 0, from: 'LIS', to: 'MAD', results: [a0, b0] }, { leg_index: 1, from: 'MAD', to: 'ROM', results: [a1] }] }
      const over = new Set([flightKey(b0), flightKey(a1)])
      render(<FlightsSection data={data} selections={{ ...emptySel, flights: [a1] }} onSelect={() => {}} budget={{ over, hideOver: true }} />)
      expect(text()).not.toContain('$500')
      expect(text()).toContain('$900')
      expect(isDimmed(cardOf('$900'))).toBe(false)
      expect(cardOf('$900').textContent).toContain('Added')
      expect((text().match(/hidden — show all/g) || []).length).toBe(1)
      render(<FlightsSection data={data} selections={emptySel} onSelect={() => {}} budget={{ over, hideOver: false }} />)
      expect(isDimmed(cardOf('$500'))).toBe(true)
      expect(cardOf('$500').textContent).toContain('Add')
      expectFullOpacityTag(cardOf('$500'))
    })
  })

  describe('ActivitiesSection', () => {
    it('tags planner picks with "Fits your budget"', () => {
      const data = { results: [{ name: 'Tram ride', category: 'culture', price_usd: 5 }, { name: 'Balloon', category: 'adventure', price_usd: 300 }] }
      render(<ActivitiesSection data={data} selections={emptySel} onSelect={() => {}} />)
      expect(text()).not.toContain('Fits your budget')
      render(<ActivitiesSection data={data} selections={emptySel} onSelect={() => {}} budget={{ picked: new Set(['Tram ride']) }} />)
      expect(cardOf('Tram ride').textContent).toContain('Fits your budget')
      expect(cardOf('Balloon').textContent).not.toContain('Fits your budget')
    })
  })
})
