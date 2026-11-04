// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import LinkPlanBanner from './LinkPlanBanner'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const SD = {
  must_include: [{ name: 'A' }, { name: 'B' }, { name: 'C' }],
  import_source: { url: 'https://blog.example/x', title: '48 hours in Lisbon' },
}

describe('LinkPlanBanner', () => {
  let container, root
  const render = (ui) => act(() => root.render(ui))
  beforeEach(() => {
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
  })
  afterEach(() => {
    act(() => root.unmount())
    container.remove()
  })

  it('celebrates when every place made it in', () => {
    render(<LinkPlanBanner searchData={SD} itinerary={{ days: [{ slots: [{ from_link: true, link_place: 'A', link_places: ['A', 'B'] }], link_extras: [{ name: 'C' }] }] }} />)
    expect(container.textContent).toContain('Planned around 3 places from')
    expect(container.textContent).toContain('48 hours in Lisbon')
    expect(container.textContent).toContain('all 3 are in your itinerary')
    expect(container.querySelector('a').href).toBe('https://blog.example/x')
  })

  it('owns up to places that did not fit and lists them on request', () => {
    render(<LinkPlanBanner searchData={SD} itinerary={{ days: [{ slots: [{ from_link: true, link_place: 'A', link_places: ['A', 'B'] }] }] }} />)
    expect(container.textContent).toContain('2 of 3 are in your itinerary')
    const show = [...container.querySelectorAll('button')].find((b) => b.textContent.includes('1 didn’t fit'))
    expect(container.textContent).not.toContain('C,')
    act(() => show.click())
    expect(container.querySelector('[data-missing]').textContent).toContain('C')
  })

  it('waits for the itinerary, then can be dismissed', () => {
    render(<LinkPlanBanner searchData={SD} itinerary={null} />)
    expect(container.textContent).toContain('Fitting your 3 places into the days')
    act(() => container.querySelector('[aria-label="Dismiss"]').click())
    expect(container.textContent).toBe('')
  })

  it('says plainly when the day plan could not be built — never a spinner', () => {
    render(<LinkPlanBanner searchData={SD} itinerary={null} failed />)
    expect(container.textContent).toContain('We couldn’t build the day plan')
    expect(container.textContent).toContain('top of Activities')
    expect(container.textContent).not.toMatch(/\bare\b[^.]*\bare\b/)
    expect(container.querySelector('.animate-spin')).toBeNull()
  })

  it('renders nothing for an ordinary search', () => {
    render(<LinkPlanBanner searchData={{}} itinerary={null} />)
    expect(container.textContent).toBe('')
  })
})
