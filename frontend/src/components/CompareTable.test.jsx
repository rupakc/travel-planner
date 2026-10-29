// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import CompareTable from './CompareTable'

vi.mock('../utils/analytics', () => ({ track: vi.fn() }))
import { track } from '../utils/analytics'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const summary = (over = {}) => ({
  destination: 'Tokyo', label: 'Tokyo',
  flight: { price_usd: 900, stops: 1, duration_minutes: 840, airline: 'ANA', source: 'estimate' },
  hotel: { typical_nightly_usd: 120, cheapest_good_nightly_usd: 80, count: 5 },
  weather: { avg_high_c: 20, avg_low_c: 12, poor_days: 2, total_days: 7, source: 'climate-table' },
  visa: { visa_type: 'Visa-free', max_stay_days: 90, fee_usd: 0, processing_time: null, verified: true },
  ease: { total: 85, grade: 'green', safety: 18, english: 10, infrastructure: 18, visa_ease: 20 },
  daily_cost_usd: 150,
  estimate: { total_usd: 2200, partial: true, budget_status: 'under' },
  missing: [],
  ...over,
})

describe('CompareTable', () => {
  let container, root
  const render = (columns, props = {}) => act(() => root.render(
    <CompareTable columns={columns} onPlan={() => {}} onRetry={() => {}} {...props} />,
  ))
  const table = () => container.querySelector('table')

  beforeEach(() => {
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
    vi.clearAllMocks()
  })
  afterEach(() => {
    act(() => root.unmount())
    container.remove()
  })

  it('renders one column per destination with labels', () => {
    render([
      { destination: 'Tokyo', status: 'done', summary: summary() },
      { destination: 'Paris', status: 'done', summary: summary({ label: 'Paris', visa: { visa_type: 'Schengen', verified: false } , weather: { avg_high_c: 18, avg_low_c: 9, poor_days: 1, total_days: 7, source: 'open-meteo' } }) },
    ])
    expect(table().querySelectorAll('thead th')).toHaveLength(3)
    const text = table().textContent
    expect(text).toContain('Tokyo')
    expect(text).toContain('Paris')
    expect(text).toContain('estimate')
    expect(text).toContain('Verified')
    expect(text).toContain('AI — check official site')
    expect(text).toContain('climate estimate')
    expect(text).toContain('partial')
    expect(text).toContain('Under budget')
    expect(text).toContain('2 of 7 days poor')
  })

  it('shows climate estimate only for non open-meteo weather', () => {
    render([{ destination: 'A', status: 'done', summary: summary({ weather: { avg_high_c: 1, avg_low_c: 0, poor_days: 0, total_days: 3, source: 'open-meteo' } }) }])
    expect(table().textContent).not.toContain('climate estimate')
  })

  it('null-safe weather temperatures', () => {
    const w = (over) => ({ avg_high_c: null, avg_low_c: null, poor_days: 1, total_days: 7, source: 'open-meteo', ...over })
    render([{ destination: 'A', status: 'done', summary: summary({ weather: w() }) }])
    const row = () => [...table().querySelectorAll('tbody tr')].find((r) => r.textContent.includes('Weather')).textContent
    expect(row()).not.toContain('0°')
    expect(row()).not.toContain('NaN')
    expect(row()).toContain('—')
    expect(row()).toContain('1 of 7 days poor')
    render([{ destination: 'A', status: 'done', summary: summary({ weather: w({ avg_high_c: 21.4 }) }) }])
    expect(row()).toContain('21°')
    expect(row()).toContain('—')
    expect(row()).not.toContain('NaN')
  })

  it('flight estimate badge appears in the flight row only when source is estimate', () => {
    render([{ destination: 'A', status: 'done', summary: summary({ weather: { avg_high_c: 1, avg_low_c: 0, poor_days: 0, total_days: 3, source: 'open-meteo' }, estimate: { total_usd: 1 }, flight: { price_usd: 900, stops: 0, duration_minutes: 60, airline: 'X', source: 'estimate' } }) }])
    const rowText = (label) => [...table().querySelectorAll('tbody tr')].find((r) => r.textContent.includes(label)).textContent
    expect(rowText('Cheapest flight')).toContain('estimate')
    expect(rowText('Weather')).not.toContain('estimate')
    expect(rowText('Hotel')).not.toContain('estimate')
  })

  it('stacked cards render labels, Best, Retry and Plan callbacks', () => {
    const onPlan = vi.fn()
    const onRetry = vi.fn()
    render([
      { destination: 'A', status: 'done', summary: summary({ estimate: { total_usd: 3000 } }) },
      { destination: 'B', status: 'done', summary: summary({ estimate: { total_usd: 2000 } }) },
      { destination: 'C', status: 'error' },
    ], { onPlan, onRetry })
    const cards = container.querySelectorAll('.md\\:hidden > div')
    expect(cards).toHaveLength(3)
    expect(cards[0].textContent).toContain('Est. trip cost / person')
    const estRow = (card) => [...card.children].find((r) => r.textContent.includes('Est. trip cost')).textContent
    expect(estRow(cards[0])).not.toContain('Best')
    expect(estRow(cards[1])).toContain('Best')
    act(() => [...cards[1].querySelectorAll('button')].find((b) => b.textContent === 'Plan this trip').click())
    expect(onPlan).toHaveBeenCalledWith(1)
    act(() => [...cards[2].querySelectorAll('button')].find((b) => b.textContent === 'Retry').click())
    expect(onRetry).toHaveBeenCalledWith(2)
  })

  it('shows dashes for null data and no Best with a single column', () => {
    render([{ destination: 'X', status: 'done', summary: summary({ flight: null, hotel: null, weather: null, visa: null, ease: null, daily_cost_usd: null }) }])
    expect(table().textContent).toContain('—')
    expect(table().textContent).not.toContain('Best')
  })

  it('marks Best on the cheaper column only', () => {
    render([
      { destination: 'A', status: 'done', summary: summary({ estimate: { total_usd: 3000 } }) },
      { destination: 'B', status: 'done', summary: summary({ estimate: { total_usd: 2000 } }) },
    ])
    const row = [...table().querySelectorAll('tbody tr')].find((r) => r.textContent.includes('Est. trip cost'))
    const cells = row.querySelectorAll('td')
    expect(cells[0].textContent).not.toContain('Best')
    expect(cells[1].textContent).toContain('Best')
  })

  it('renders loading skeleton and error with Retry', () => {
    const onRetry = vi.fn()
    render([
      { destination: 'A', status: 'loading' },
      { destination: 'B', status: 'error', error: 'boom' },
    ], { onRetry })
    expect(table().querySelectorAll('[data-testid="compare-skeleton"]').length).toBeGreaterThan(0)
    expect(table().textContent).toContain('Couldn')
    const retry = [...table().querySelectorAll('button')].find((b) => b.textContent === 'Retry')
    act(() => retry.click())
    expect(onRetry).toHaveBeenCalledWith(1)
  })

  it('Plan this trip calls onPlan with the column index and tracks', () => {
    const onPlan = vi.fn()
    render([
      { destination: 'A', status: 'done', summary: summary() },
      { destination: 'B', status: 'done', summary: summary() },
    ], { onPlan })
    const buttons = [...table().querySelectorAll('button')].filter((b) => b.textContent === 'Plan this trip')
    expect(buttons).toHaveLength(2)
    act(() => buttons[1].click())
    expect(onPlan).toHaveBeenCalledWith(1)
    expect(track).toHaveBeenCalledWith('compare_plan_clicked', 'search', { position: 1 })
  })

  it('colours the Travel Ease grade from the backend green/amber/red value', () => {
    const easeCell = (grade) => {
      render([{ destination: 'A', status: 'done', summary: summary({ ease: { total: 50, grade, safety: 10, english: 10 } }) }])
      return [...table().querySelectorAll('tbody tr')].find((r) => r.textContent.includes('Travel Ease')).querySelector('td')
    }
    expect(easeCell('green').innerHTML).toContain('emerald')
    expect(easeCell('green').textContent).toContain('Easy')
    expect(easeCell('amber').innerHTML).toContain('amber')
    expect(easeCell('amber').textContent).toContain('Moderate')
    expect(easeCell('red').innerHTML).toContain('red')
    expect(easeCell('red').textContent).toContain('Hard')
    for (const g of ['green', 'amber', 'red']) expect(easeCell(g).textContent).not.toContain(g)
    expect(easeCell('weird').textContent).toBe('50/100')
  })

  it('labels per-person cost rows', () => {
    render([{ destination: 'A', status: 'done', summary: summary() }])
    const labels = [...table().querySelectorAll('tbody th')].map((th) => th.textContent)
    expect(labels).toContain('Est. trip cost / person')
    expect(labels).toContain('Cheapest flight / person')
    expect(labels).toContain('Typical daily spend / person')
  })

  it('shows the stored failure reason under Couldn\'t load', () => {
    render([{ destination: 'A', status: 'error', error: 'Please check the trip details' }, { destination: 'B', status: 'error', error: { detail: 'obj' } }])
    const heads = table().querySelectorAll('thead th')
    expect(heads[1].textContent).toContain('Please check the trip details')
    expect(heads[2].textContent).not.toContain('[object Object]')
    expect(heads[2].textContent).toContain('Couldn')
  })

  it('also renders stacked cards for mobile', () => {
    render([{ destination: 'A', status: 'done', summary: summary() }])
    expect(container.querySelector('.md\\:hidden')).not.toBeNull()
  })
})
