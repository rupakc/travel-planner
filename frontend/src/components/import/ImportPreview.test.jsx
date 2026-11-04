// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'

vi.mock('./ImportMap', () => ({ default: ({ places }) => <div data-map>{places.length} pins</div> }))
vi.mock('../ui/AirportSearch', () => ({ default: ({ value, onChange }) => <input data-origin value={value} onChange={(e) => onChange(e.target.value)} /> }))
vi.mock('../ui/NationalitySearch', () => ({ default: ({ value, onChange }) => <input data-nationality value={value} onChange={(e) => onChange(e.target.value)} /> }))
vi.mock('../ui/TravelerPanel', () => ({ default: () => <div data-travelers /> }))
vi.mock('../../services/api', () => ({ resolveImportPlace: vi.fn() }))

import ImportPreview from './ImportPreview'
import { resolveImportPlace } from '../../services/api'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const PREVIEW = {
  source: { kind: 'url', url: 'https://wander.example/lisbon', title: '48 Hours in Lisbon | Wander', site_name: 'Wander Blog', favicon_url: 'https://wander.example/fav.png', author: 'Ana' },
  title: '48 hours in Lisbon',
  summary: 'Viewpoints, pastries and a day in Sintra.',
  destinations: [
    { name: 'Lisbon, Portugal', city: 'Lisbon', country: 'Portugal', airports: ['LIS'], place_count: 3, nights: 2 },
    { name: 'Porto, Portugal', city: 'Porto', country: 'Portugal', airports: ['OPO'], place_count: 1, nights: 1 },
  ],
  places: [
    { id: 'p1', name: 'Time Out Market', kind: 'food', city: 'Lisbon', destination: 'Lisbon, Portugal', lat: 38.7, lng: -9.1, approximate: false, verified: true, note: 'Lunch under one roof', quote: 'start at Time Out Market' },
    { id: 'p2', name: 'Belem Tower', kind: 'sight', city: 'Lisbon', destination: 'Lisbon, Portugal', lat: 38.7, lng: -9.1, approximate: true },
    { id: 'p3', name: 'Pena Palace', kind: 'sight', city: 'Sintra', destination: 'Lisbon, Portugal', lat: 38.8, lng: -9.4, approximate: true },
    { id: 'p4', name: 'Livraria Lello', kind: 'shopping', city: 'Porto', destination: 'Porto, Portugal', lat: 41.1, lng: -8.6, approximate: true },
  ],
  unresolved: [{ id: 'p5', name: 'Mystery Bar', kind: 'drink', city: 'Xqz' }],
  suggested_days: 3,
  interests: ['food'],
  warnings: ["We couldn't place 1 spot on the map — add a city to include them."],
}

const FORM = { origin: 'London', nationality: 'British', interests: ['history'], adults: 1, children: 0, seniors: 0, infants: 0, budget_usd: '' }

describe('ImportPreview', () => {
  let container, root, onPlan, onStartOver
  const render = (props = {}) => act(() => root.render(
    <ImportPreview preview={PREVIEW} form={FORM} today="2026-11-04" onPlan={onPlan} onStartOver={onStartOver} {...props} />,
  ))
  const btn = (text) => [...container.querySelectorAll('button')].find((b) => b.textContent.includes(text))
  const planButton = () => btn('Plan this trip')
  const box = (name) => container.querySelector(`input[type="checkbox"][aria-label="Include ${name}"]`)

  beforeEach(() => {
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
    onPlan = vi.fn()
    onStartOver = vi.fn()
  })
  afterEach(() => {
    act(() => root.unmount())
    container.remove()
  })

  it('shows what was found and where it came from', () => {
    render()
    expect(container.querySelector('h2').textContent).toBe('48 hours in Lisbon')
    expect(container.textContent).toContain('Viewpoints, pastries')
    const source = container.querySelector('a[href="https://wander.example/lisbon"]')
    expect(source).not.toBeNull()
    expect(source.rel).toContain('noopener')
    expect(container.textContent).toContain('Wander Blog')
    expect(container.textContent).toContain('“start at Time Out Market”')
    expect(container.textContent).toContain('Sintra') // day trip town shown
    expect(container.textContent).toContain("Couldn't place")
    expect(planButton().textContent).toContain('4 places')
    expect(container.querySelector('[data-map]').textContent).toBe('4 pins')
  })

  it('unticking a place updates the plan button and the map', () => {
    render()
    act(() => box('Belem Tower').click())
    expect(planButton().textContent).toContain('3 places')
    expect(container.querySelector('[data-map]').textContent).toBe('3 pins')
  })

  it('selects none / all per city', () => {
    render()
    act(() => container.querySelector('[aria-label="Select none in Lisbon"]').click())
    expect(planButton().textContent).toContain('1 place')
    act(() => container.querySelector('[aria-label="Select all in Lisbon"]').click())
    expect(planButton().textContent).toContain('4 places')
  })

  it('renames a place inline', () => {
    render()
    act(() => container.querySelector('[aria-label="Rename Belem Tower"]').click())
    const input = container.querySelector('input[aria-label="New name for Belem Tower"]')
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set
    act(() => { setter.call(input, 'Belém Tower'); input.dispatchEvent(new Event('input', { bubbles: true })) })
    act(() => input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })))
    expect(container.textContent).toContain('Belém Tower')
    act(() => planButton().click())
    expect(onPlan.mock.calls[0][0].form.must_include.map((p) => p.name)).toContain('Belém Tower')
  })

  it('places an unplaced spot by choosing its stop', () => {
    render()
    const select = container.querySelector('select[aria-label="Which stop is Mystery Bar in?"]')
    act(() => {
      select.value = 'Porto, Portugal'
      select.dispatchEvent(new Event('change', { bubbles: true }))
    })
    expect(planButton().textContent).toContain('5 places')
  })

  it('adjusts nights per stop and shows the return date', () => {
    render()
    expect(container.textContent).toContain('3 nights')
    act(() => container.querySelector('[aria-label="One more night in Lisbon"]').click())
    expect(container.textContent).toContain('4 nights')
    act(() => planButton().click())
    const { form, stops, placeCount } = onPlan.mock.calls[0][0]
    expect(stops).toEqual([{ city: 'Lisbon, Portugal', nights: 3 }])
    expect(form.destination).toBe('Porto, Portugal')
    expect(form.departure_date).toBe('2026-12-04')
    expect(form.return_date).toBe('2026-12-08')
    expect(form.origin).toBe('London')
    expect(form.interests).toEqual(['history', 'food'])
    expect(form.import_source).toEqual({ url: 'https://wander.example/lisbon', title: '48 hours in Lisbon' })
    expect(placeCount).toBe(4)
  })

  it('needs an origin and nationality before planning', () => {
    render({ form: { ...FORM, origin: '', nationality: '' } })
    expect(planButton().disabled).toBe(true)
    expect(container.textContent).toContain('Add where you’re flying from')
  })

  it('starts over', () => {
    render()
    act(() => btn('Start over').click())
    expect(onStartOver).toHaveBeenCalled()
  })
})


describe('ImportPreview review fixes', () => {
  let container, root, onPlan
  const render = (props = {}) => act(() => root.render(
    <ImportPreview preview={PREVIEW} form={FORM} today="2026-11-04" token="tok" onPlan={onPlan} onStartOver={() => {}} {...props} />,
  ))
  const btn = (text) => [...container.querySelectorAll('button')].find((b) => b.textContent.includes(text))
  const typeInto = (input, value) => {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set
    act(() => { setter.call(input, value); input.dispatchEvent(new Event('input', { bubbles: true })) })
  }
  beforeEach(() => {
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
    onPlan = vi.fn()
    resolveImportPlace.mockReset()
  })
  afterEach(() => {
    act(() => root.unmount())
    container.remove()
  })

  it('places an unplaced spot in a town the traveller types, adding it as a stop', async () => {
    resolveImportPlace.mockResolvedValue({
      place: { id: 'p5', name: 'Mystery Bar', kind: 'drink', city: 'Faro', destination: 'Faro, Portugal', lat: 37, lng: -7.9, approximate: true },
      destination: { name: 'Faro, Portugal', city: 'Faro', country: 'Portugal', airports: ['FAO'], place_count: 1, nights: 1 },
    })
    render()
    typeInto(container.querySelector('input[aria-label="Town for Mystery Bar"]'), 'Faro')
    await act(async () => { btn('Place it').click() })
    expect(resolveImportPlace).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'p5', name: 'Mystery Bar', city: 'Faro' }), 'tok',
    )
    expect(container.textContent).not.toContain("Couldn't place")
    expect(btn('Plan this trip').textContent).toContain('5 places')
    act(() => btn('Plan this trip').click())
    const { form, stops } = onPlan.mock.calls[0][0]
    expect(form.destination).toBe('Faro, Portugal')
    expect(stops.map((s) => s.city)).toEqual(['Lisbon, Portugal', 'Porto, Portugal'])
    expect(form.must_include.at(-1)).toMatchObject({ name: 'Mystery Bar', city: 'Faro' })
  })

  it('shows the server\'s message when the town is unknown', async () => {
    resolveImportPlace.mockRejectedValue({ response: { status: 422, data: { detail: { code: 'city_not_found', message: 'We couldn’t find a town called “Xqz”.' } } } })
    render()
    typeInto(container.querySelector('input[aria-label="Town for Mystery Bar"]'), 'Xqz')
    await act(async () => { btn('Place it').click() })
    expect(container.textContent).toContain('We couldn’t find a town called “Xqz”.')
    expect(container.textContent).toContain("Couldn't place")
  })

  it('cannot plan with nothing ticked', () => {
    render()
    act(() => container.querySelector('[aria-label="Select none in Lisbon"]').click())
    act(() => container.querySelector('[aria-label="Select none in Porto"]').click())
    expect(btn('Plan this trip').disabled).toBe(true)
    expect(container.textContent).toContain('Tick at least one place')
  })

  it('makes "change stop" a visible, labelled control', () => {
    render()
    const select = container.querySelector('select[aria-label="Stop for Belem Tower"]')
    expect(select).not.toBeNull()
    expect(select.className).toContain('border')
  })
})
