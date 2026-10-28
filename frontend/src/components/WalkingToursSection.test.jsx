// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import WalkingToursSection, { WalkingTourPlanRow } from './WalkingToursSection'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const tour = (over = {}) => ({
  id: 'guruwalk-barcelona-0',
  name: 'Free Tour of the Old Town',
  provider: 'GuruWalk',
  provider_key: 'guruwalk',
  url: 'https://www.guruwalk.com/walks/564-free-tour',
  image_url: 'https://media.guruwalk.com/a.jpg',
  description: 'desc',
  rating: 4.9,
  review_count: 1234,
  duration: '2h 30m',
  price_note: 'Free · tip-based',
  city: 'Barcelona',
  reason: null,
  top_pick: false,
  ...over,
})

describe('WalkingToursSection', () => {
  let container, root
  const render = (props) => act(() => root.render(
    <WalkingToursSection selections={{}} onSelect={() => {}} {...props} />,
  ))

  beforeEach(() => {
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
  })
  afterEach(() => {
    act(() => root.unmount())
    container.remove()
    vi.restoreAllMocks()
  })

  it('renders a card per tour linking to the original page', () => {
    const t = tour()
    render({ data: { results: [t], sources: [] } })
    const name = [...container.querySelectorAll('a')].find(a => a.textContent === t.name)
    const view = [...container.querySelectorAll('a')].find(a => a.textContent.includes('View on GuruWalk'))
    for (const a of [name, view]) {
      expect(a.getAttribute('href')).toBe(t.url)
      expect(a.getAttribute('target')).toBe('_blank')
      expect(a.getAttribute('rel')).toContain('noopener')
      expect(a.getAttribute('rel')).toContain('noreferrer')
    }
    expect(container.textContent).toContain('(1,234 reviews)')
    expect(container.textContent).toContain('2h 30m')
    expect(container.textContent).toContain('Free · tip-based')
    const img = container.querySelector('img')
    expect(img.getAttribute('referrerpolicy')).toBe('no-referrer')
  })

  it('walking tours card never renders unsafe links', () => {
    render({ data: { results: [tour({ url: 'javascript:alert(1)', image_url: 'javascript:x' })], sources: [{ provider: 'GuruWalk', provider_key: 'guruwalk', city: 'B', url: '', count: 3, status: 'ok' }] } })
    expect(container.querySelector('a[href^="javascript"]')).toBeNull()
    expect(container.querySelectorAll('a').length).toBe(0)
    expect(container.querySelector('img')).toBeNull()
    expect(container.textContent).toContain('Free Tour of the Old Town')
    expect(container.textContent).toContain('GuruWalk (3)')
  })

  it('shows top picks first and their reasons', () => {
    const results = [
      tour({ name: 'Plain', url: 'https://www.guruwalk.com/a' }),
      tour({ name: 'Star', url: 'https://www.guruwalk.com/b', top_pick: true, reason: 'Matches your history interest' }),
    ]
    const copy = JSON.parse(JSON.stringify(results))
    render({ data: { results, sources: [] } })
    const names = [...container.querySelectorAll('h3')].map(h => h.textContent)
    expect(names).toEqual(['Star', 'Plain'])
    expect(container.textContent).toContain('Top pick')
    const reason = container.querySelector('p.italic')
    expect(reason.textContent).toContain('Matches your history interest')
    expect(results).toEqual(copy)
  })

  it('shows city chips only for multi-city results', () => {
    render({ data: { results: [tour(), tour({ url: 'https://www.guruwalk.com/z' })], sources: [] } })
    expect(container.querySelector('[data-testid="city-chip"]')).toBeNull()
    render({ data: { results: [tour(), tour({ url: 'https://www.guruwalk.com/z', city: 'Madrid' })], sources: [] } })
    expect(container.querySelectorAll('[data-testid="city-chip"]').length).toBe(2)
  })

  it('Add toggles selection via onSelect', () => {
    const onSelect = vi.fn()
    const t = tour()
    render({ data: { results: [t], sources: [] }, onSelect })
    const btn = container.querySelector('button')
    expect(btn.getAttribute('aria-label')).toContain(t.name)
    expect(btn.textContent).toContain('Add')
    act(() => btn.click())
    expect(onSelect).toHaveBeenCalledWith('walking_tours', t)
    render({ data: { results: [t], sources: [] }, onSelect, selections: { walking_tours: [{ url: t.url }] } })
    expect(container.querySelector('button').textContent).toContain('Added')
  })

  it('error and empty states', () => {
    render({ data: { error: 'boom' } })
    expect(container.textContent).toContain("Couldn't reach the walking-tour sites this time — the rest of your plan is unaffected.")
    render({ data: { results: [], sources: [] } })
    expect(container.textContent).toContain('No free walking tours listed for this destination on GuruWalk, FreeTour.com, SANDEMANs or FreeWalkingTour.com.')
  })

  it('lists searched sources with counts', () => {
    const sources = [
      { provider: 'GuruWalk', provider_key: 'guruwalk', city: 'Barcelona', url: 'https://www.guruwalk.com/barcelona', count: 10, status: 'ok' },
      { provider: 'FreeTour.com', provider_key: 'freetour', city: 'Barcelona', url: 'https://www.freetour.com/barcelona', count: 7, status: 'ok' },
    ]
    render({ data: { results: [tour()], sources } })
    expect(container.textContent).toContain('Searched: GuruWalk (10) · FreeTour.com (7)')
    const a = [...container.querySelectorAll('a')].find(x => x.textContent.includes('GuruWalk (10)'))
    expect(a.getAttribute('href')).toBe('https://www.guruwalk.com/barcelona')
    expect(a.getAttribute('rel')).toContain('noopener')
  })

  it('sorts top picks first within each city, keeping journey order', () => {
    const results = [
      tour({ name: 'Lisbon plain', url: 'https://www.guruwalk.com/l1', city: 'Lisbon' }),
      tour({ name: 'Lisbon star', url: 'https://www.guruwalk.com/l2', city: 'Lisbon', top_pick: true }),
      tour({ name: 'Porto plain', url: 'https://www.guruwalk.com/p1', city: 'Porto' }),
      tour({ name: 'Porto star', url: 'https://www.guruwalk.com/p2', city: 'Porto', top_pick: true }),
      tour({ name: 'Lisbon late', url: 'https://www.guruwalk.com/l3', city: 'Lisbon' }),
    ]
    render({ data: { results, sources: [] } })
    const names = [...container.querySelectorAll('h3')].map(h => h.textContent)
    expect(names).toEqual(['Lisbon star', 'Lisbon plain', 'Lisbon late', 'Porto star', 'Porto plain'])
  })

  it('links only ok sources and labels none/error sources', () => {
    const sources = [
      { provider: 'GuruWalk', provider_key: 'guruwalk', city: 'Lisbon', url: 'https://www.guruwalk.com/lisbon', count: 10, status: 'ok' },
      { provider: 'FreeTour.com', provider_key: 'freetour', city: 'Lisbon', url: 'https://www.freetour.com/lisbon', count: 0, status: 'none' },
      { provider: 'SANDEMANs NewEurope', provider_key: 'sandemans', city: 'Lisbon', url: 'https://www.neweuropetours.eu/sandemans-tours/lisbon/', count: 0, status: 'error' },
    ]
    render({ data: { results: [tour({ city: 'Lisbon' })], sources } })
    const footer = container.querySelector('[data-testid="walking-tours-sources"]')
    expect(footer.textContent).toContain('GuruWalk (10)')
    expect(footer.textContent).toContain('FreeTour.com (0)')
    expect(footer.textContent).toContain('SANDEMANs NewEurope (unavailable)')
    const links = [...footer.querySelectorAll('a')]
    expect(links.map(a => a.textContent)).toEqual(['GuruWalk (10)'])
    expect(links[0].getAttribute('href')).toBe('https://www.guruwalk.com/lisbon')
  })

  it('shows the city in source labels for multi-city results', () => {
    const sources = [
      { provider: 'GuruWalk', provider_key: 'guruwalk', city: 'Lisbon', url: 'https://www.guruwalk.com/lisbon', count: 10, status: 'ok' },
      { provider: 'GuruWalk', provider_key: 'guruwalk', city: 'Porto', url: 'https://www.guruwalk.com/porto', count: 0, status: 'none' },
    ]
    const results = [tour({ city: 'Lisbon' }), tour({ city: 'Porto', url: 'https://www.guruwalk.com/p' })]
    render({ data: { results, sources } })
    const footer = container.querySelector('[data-testid="walking-tours-sources"]')
    expect(footer.textContent).toContain('GuruWalk · Lisbon (10)')
    expect(footer.textContent).toContain('GuruWalk · Porto (0)')
    expect([...footer.querySelectorAll('a')].map(a => a.textContent)).toEqual(['GuruWalk · Lisbon (10)'])
  })
})

describe('WalkingTourPlanRow', () => {
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

  it('links a safe url', () => {
    act(() => root.render(<WalkingTourPlanRow tour={tour()} onRemove={() => {}} />))
    const a = container.querySelector('a')
    expect(a.getAttribute('href')).toBe('https://www.guruwalk.com/walks/564-free-tour')
    expect(a.getAttribute('rel')).toContain('noopener')
  })

  it('renders no url text at all when the url is unsafe', () => {
    act(() => root.render(<WalkingTourPlanRow tour={tour({ url: 'javascript:alert(1)' })} onRemove={() => {}} />))
    expect(container.querySelector('a')).toBeNull()
    expect(container.textContent).not.toContain('javascript')
    expect(container.textContent).toContain('Free Tour of the Old Town')
    expect(container.textContent).toContain('GuruWalk')
  })

  it('remove button calls onRemove with the tour', () => {
    const onRemove = vi.fn()
    const t = tour()
    act(() => root.render(<WalkingTourPlanRow tour={t} onRemove={onRemove} />))
    act(() => container.querySelector('button').click())
    expect(onRemove).toHaveBeenCalledWith(t)
  })
})
