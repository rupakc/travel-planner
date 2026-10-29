// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { act, useEffect } from 'react'
import { createRoot } from 'react-dom/client'
import { FlightsSection } from './ResultsPage'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const emptySel = { flight: null, flights: [], hotel: null, activities: [], places_to_see: [] }
const rt = (n, price) => ({
  price_usd: price,
  outbound: { airline: 'Air', flight_number: n, stops: 0, duration_minutes: 600 },
  return: { airline: 'Air', flight_number: `${n}r`, stops: 0, duration_minutes: 600 },
})
const legacy = (n, price) => ({ airline: `Air${n}`, flight_number: n, price_usd: price, stops: 0 })
const INSIGHTS = { price_level: 'high', typical_price_range: [420, 610] }
const CHIP = 'Fares are high right now · typical $420–$610'

describe('FlightsSection fare insights', () => {
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

  it('shows the Google Flights price-level chip on round-trip cards', () => {
    render(<FlightsSection data={{ results: [rt('1', 500)], price_insights: INSIGHTS }} selections={emptySel} onSelect={() => {}} />)
    expect(container.querySelector('[data-level="high"]').textContent).toContain(CHIP)
  })

  it('shows the chip on the legacy table layout too', () => {
    render(<FlightsSection data={{ results: [legacy('1', 500)], price_insights: INSIGHTS }} selections={emptySel} onSelect={() => {}} />)
    expect(container.textContent).toContain(CHIP)
  })

  it('shows no chip without price insights', () => {
    render(<FlightsSection data={{ results: [rt('1', 500)] }} selections={emptySel} onSelect={() => {}} />)
    expect(container.textContent).not.toContain('Fares are')
  })

  it('renders the fare calendar slot above the flights', () => {
    render(<FlightsSection data={{ results: [rt('1', 500)] }} selections={emptySel} onSelect={() => {}}
      fareCalendar={<div data-testid="fare-slot">calendar</div>} />)
    const slot = container.querySelector('[data-testid="fare-slot"]')
    expect(slot).not.toBeNull()
    const firstCard = [...container.querySelectorAll('.rounded-xl')].find(c => c.textContent.includes('Round-trip'))
    expect(slot.compareDocumentPosition(firstCard) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('still offers the fare calendar when no flights were found', () => {
    render(<FlightsSection data={{ results: [] }} selections={emptySel} onSelect={() => {}}
      fareCalendar={<div data-testid="fare-slot">calendar</div>} />)
    expect(container.querySelector('[data-testid="fare-slot"]')).not.toBeNull()
    expect(container.textContent).toContain('No flights found')
  })

  it('keeps the fare calendar mounted when results arrive or change layout', () => {
    let mounts = 0
    function Probe() {
      useEffect(() => { mounts += 1 }, [])
      return <div data-testid="fare-slot">calendar</div>
    }
    const props = { selections: emptySel, onSelect: () => {}, fareCalendar: <Probe /> }
    render(<FlightsSection data={{ results: [] }} {...props} />)
    render(<FlightsSection data={{ results: [rt('1', 500)], price_insights: INSIGHTS }} {...props} />)
    render(<FlightsSection data={{ results: [legacy('1', 500)] }} {...props} pricingData={null} />)
    render(<FlightsSection data={{ results: [] }} {...props} />)
    expect(mounts).toBe(1)
    expect(container.querySelector('[data-testid="fare-slot"]')).not.toBeNull()
  })
})
