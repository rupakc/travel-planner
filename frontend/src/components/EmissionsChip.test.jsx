// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import '../i18n'
import EmissionsChip from './EmissionsChip'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const EMISSIONS = {
  kg_co2e_per_pax: 134,
  cabin: 'economy',
  by_class: { economy: 134, premiumEconomy: 134, business: 201, first: 201 },
  source: 'Google Travel Impact Model',
  attribution_url: 'https://travelimpactmodel.org',
}

describe('EmissionsChip', () => {
  let container, root
  const render = (props) => act(() => root.render(<EmissionsChip {...props} />))
  const chip = () => container.querySelector('[data-tid="results.flight.emissions"]')

  beforeEach(() => {
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
  })
  afterEach(() => {
    act(() => root.unmount())
    container.remove()
  })

  it('renders nothing without emissions (older backend or feature off)', () => {
    render({})
    expect(container.innerHTML).toBe('')
    render({ emissions: { kg_co2e_per_pax: 'n/a' } })
    expect(container.innerHTML).toBe('')
  })

  it('shows the per-passenger estimate and links to TIM', () => {
    render({ emissions: EMISSIONS })
    expect(chip().textContent).toBe('≈ 134 kg CO₂e')
    expect(chip().getAttribute('href')).toBe('https://travelimpactmodel.org')
    expect(chip().getAttribute('target')).toBe('_blank')
  })

  it('tooltip gives the class breakdown and the attribution', () => {
    render({ emissions: EMISSIONS })
    const title = chip().getAttribute('title')
    expect(title).toContain('Business: 201 kg')
    expect(title).toContain('Premium economy: 134 kg')
    expect(title).toContain('Emissions estimates: Google Travel Impact Model')
  })

  it('clicking the chip does not select the flight card', () => {
    let selected = false
    act(() => root.render(<div onClick={() => { selected = true }}><EmissionsChip emissions={EMISSIONS} /></div>))
    act(() => chip().dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true })))
    expect(selected).toBe(false)
  })
})
