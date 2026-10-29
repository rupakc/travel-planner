// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import FareCalendarStrip, { PriceInsightsChip } from './FareCalendarStrip'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const searchData = { origin: 'JFK', destination: 'NRT', departure_date: '2026-11-03', return_date: '2026-11-10', nationality: 'American' }

const day = (dep, ret, price, selected = false) => ({ departure_date: dep, return_date: ret, cheapest_usd: price, is_selected: selected })
const CALENDAR = {
  currency: 'USD', source: 'google_flights',
  dates: [
    day('2026-10-31', '2026-11-07', 610),
    day('2026-11-01', '2026-11-08', 520),
    day('2026-11-02', '2026-11-09', null),
    day('2026-11-03', '2026-11-10', 565, true),
    day('2026-11-04', '2026-11-11', 590),
    day('2026-11-05', '2026-11-12', 640),
    day('2026-11-06', '2026-11-13', 700),
  ],
}

const flush = () => act(async () => { await Promise.resolve() })

describe('FareCalendarStrip', () => {
  let container, root

  const render = async (props) => {
    await act(async () => root.render(<FareCalendarStrip searchData={searchData} token="t" onReplan={() => {}} {...props} />))
    await flush()
  }
  const cells = () => [...container.querySelectorAll('[data-testid="fare-cell"]')]
  const cellFor = (date) => cells().find(c => c.dataset.date === date)
  const click = (el) => act(() => el.dispatchEvent(new MouseEvent('click', { bubbles: true })))

  beforeEach(() => {
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
  })

  afterEach(() => {
    act(() => root.unmount())
    container.remove()
  })

  it('shows a loading skeleton, then seven priced cells', async () => {
    let resolve
    const load = vi.fn(() => new Promise(r => { resolve = r }))
    await render({ load })
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull()
    expect(load).toHaveBeenCalledWith(searchData, 't')
    await act(async () => resolve(CALENDAR))
    expect(container.querySelector('[aria-busy="true"]')).toBeNull()
    expect(cells()).toHaveLength(7)
    expect(cellFor('2026-11-01').textContent).toContain('Sun')
    expect(cellFor('2026-11-01').textContent).toContain('1 Nov')
    expect(cellFor('2026-11-01').textContent).toContain('$520')
    expect(cellFor('2026-11-02').textContent).toContain('—')
  })

  it('highlights the cheapest date, outlines the selected one and shows deltas', async () => {
    await render({ load: vi.fn().mockResolvedValue(CALENDAR) })
    expect(cellFor('2026-11-01').dataset.cheapest).toBe('true')
    expect(cellFor('2026-11-04').dataset.cheapest).toBe('false')
    expect(cellFor('2026-11-03').getAttribute('aria-current')).toBe('date')
    expect(cellFor('2026-11-01').textContent).toContain('−$45')
    expect(cellFor('2026-11-06').textContent).toContain('+$135')
    expect(cellFor('2026-11-03').textContent).not.toContain('same')
  })

  it('shows the API detail (e.g. 429) with a working Retry', async () => {
    const err = { response: { status: 429, data: { detail: 'Too many requests — please wait 60 seconds and try again.' } } }
    const load = vi.fn().mockRejectedValueOnce(err).mockResolvedValueOnce(CALENDAR)
    await render({ load })
    const alert = container.querySelector('[role="alert"]')
    expect(alert.textContent).toContain('Too many requests — please wait 60 seconds and try again.')
    const retry = [...alert.querySelectorAll('button')].find(b => b.textContent === 'Retry')
    await click(retry)
    await flush()
    expect(load).toHaveBeenCalledTimes(2)
    expect(cells()).toHaveLength(7)
  })

  it('falls back to a generic message without a string detail', async () => {
    await render({ load: vi.fn().mockRejectedValue(new Error('Network Error')) })
    expect(container.querySelector('[role="alert"]').textContent).toContain("Couldn't load the fare calendar.")
  })

  it('confirms inline before re-planning on another date', async () => {
    const onReplan = vi.fn()
    await render({ load: vi.fn().mockResolvedValue(CALENDAR), onReplan })
    await click(cellFor('2026-11-01'))
    const confirm = container.querySelector('[data-testid="fare-replan-confirm"]')
    expect(confirm.textContent).toContain('Re-plan for Sun 1 Nov – Sun 8 Nov? This runs a new search.')

    await click([...confirm.querySelectorAll('button')].find(b => b.textContent === 'Cancel'))
    expect(container.querySelector('[data-testid="fare-replan-confirm"]')).toBeNull()
    expect(onReplan).not.toHaveBeenCalled()

    await click(cellFor('2026-11-01'))
    const again = container.querySelector('[data-testid="fare-replan-confirm"]')
    await click([...again.querySelectorAll('button')].find(b => b.textContent === 'Re-plan'))
    expect(onReplan).toHaveBeenCalledWith({ departure_date: '2026-11-01', return_date: '2026-11-08', offset: -2 })
  })

  it('does nothing when the selected date is clicked', async () => {
    await render({ load: vi.fn().mockResolvedValue(CALENDAR) })
    await click(cellFor('2026-11-03'))
    expect(container.querySelector('[data-testid="fare-replan-confirm"]')).toBeNull()
  })

  it('says so when no dates can be compared', async () => {
    await render({ load: vi.fn().mockResolvedValue({ ...CALENDAR, dates: [] }) })
    expect(container.textContent).toContain('No nearby dates to compare.')
  })
})

describe('PriceInsightsChip', () => {
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

  it('renders the Google Flights price level', () => {
    act(() => root.render(<PriceInsightsChip insights={{ price_level: 'low', typical_price_range: [420, 610] }} />))
    const chip = container.querySelector('[data-level="low"]')
    expect(chip.textContent).toContain('Fares are low right now · typical $420–$610')
  })

  it('renders nothing without usable insights', () => {
    act(() => root.render(<PriceInsightsChip insights={{ lowest_price: 300 }} />))
    expect(container.innerHTML).toBe('')
  })
})
