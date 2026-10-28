// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import WalkingToursSection from './WalkingToursSection'

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
})
