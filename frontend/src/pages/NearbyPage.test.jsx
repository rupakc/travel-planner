// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'

const auth = { token: 'tok', user: { username: 'u' }, preferences: {} }
vi.mock('../context/AuthContext', () => ({ useAuth: () => auth }))
vi.mock('../services/api', () => ({ fetchNearby: vi.fn() }))
vi.mock('../utils/analytics', () => ({ track: vi.fn() }))

import * as api from '../services/api'
import NearbyPage, { GEO_WATCHDOG_MS } from './NearbyPage'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const DATA = {
  place: { name: 'Lisbon', region: 'LISBON', country: 'Portugal', country_code: 'PT', lat: 38.72, lng: -9.14, distance_km: 0.4 },
  sections: [
    { id: 'see', title: 'Places to see', items: [
      { name: 'Belém Tower', summary: 'A 16th-century fort on the river.', maps_uri: 'https://maps.google.com/?cid=1', place_id: 'p1', category: 'see' },
    ] },
    { id: 'eat', title: 'Places to eat', items: [
      { name: 'Time Out Market', summary: 'Food hall with local stalls.', maps_uri: 'https://maps.google.com/?cid=2', place_id: 'p2', category: 'eat' },
      { name: 'Sneaky', summary: 'Bad link', maps_uri: 'javascript:alert(1)', place_id: 'p3', category: 'eat' },
    ] },
    { id: 'shop', title: 'Places to shop', items: [] },
    { id: 'stay', title: 'Places to stay', items: [] },
  ],
  attribution: 'Google Maps',
  sources: [{ title: 'Belém Tower', uri: 'https://maps.google.com/?cid=1' }],
}

let container, root, geo
const button = (text) => [...container.querySelectorAll('button')].find(b => b.textContent.includes(text))
const click = async (el) => { await act(async () => { el.click() }) }
const flush = async () => { await act(async () => { await new Promise(r => setTimeout(r, 0)) }) }
const success = () => geo.getCurrentPosition.mockImplementation((ok) => ok({ coords: { latitude: 38.722345, longitude: -9.139612 } }))

beforeEach(async () => {
  vi.clearAllMocks()
  geo = { getCurrentPosition: vi.fn() }
  Object.defineProperty(navigator, 'geolocation', { value: geo, configurable: true })
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  await act(async () => root.render(<NearbyPage />))
})
afterEach(() => {
  act(() => root.unmount())
  container.remove()
  vi.restoreAllMocks()
})

describe('NearbyPage', () => {
  it('explains before asking for location', () => {
    expect(container.textContent).toMatch(/Use your location\?/)
    expect(container.textContent).toMatch(/isn’t saved/)
    expect(geo.getCurrentPosition).not.toHaveBeenCalled()
  })

  it('renders the place, four sections, Maps links, attribution and sources', async () => {
    success()
    api.fetchNearby.mockResolvedValue(DATA)
    await click(button('Use my location'))
    await flush()

    expect(api.fetchNearby).toHaveBeenCalledWith({ lat: 38.722, lng: -9.14, language: navigator.language || 'en' }, 'tok')
    expect(container.querySelector('h2').textContent).toBe('Lisbon, Portugal') // the region repeats the name
    for (const id of ['see', 'eat', 'shop', 'stay']) {
      expect(container.querySelector(`[data-testid="nearby-section-${id}"]`)).not.toBeNull()
    }
    const see = container.querySelector('[data-testid="nearby-section-see"]')
    expect(see.textContent).toMatch(/Belém Tower/)
    expect(see.textContent).toMatch(/16th-century fort/)
    const link = [...see.querySelectorAll('a')].find(a => a.textContent.includes('Open in Google Maps'))
    expect(link.getAttribute('href')).toBe('https://maps.google.com/?cid=1')
    expect(link.getAttribute('target')).toBe('_blank')
    expect(link.getAttribute('rel')).toBe('noopener noreferrer')

    // An unsafe link is never rendered
    const eat = container.querySelector('[data-testid="nearby-section-eat"]')
    expect(eat.querySelectorAll('a')).toHaveLength(1)
    expect(container.innerHTML).not.toMatch(/javascript:/)

    // Empty sections say so
    expect(container.querySelector('[data-testid="nearby-section-shop"]').textContent).toMatch(/No shops turned up/)
    expect(container.querySelector('[data-testid="nearby-section-stay"]').textContent).toMatch(/No places to stay turned up/)

    expect(container.querySelector('[data-testid="nearby-attribution"]').textContent).toMatch(/Google Maps/)
    expect(container.textContent).toMatch(/Sources/)
    expect(container.querySelector('[data-testid="nearby-status"]').textContent).toMatch(/Found 3 places near Lisbon/)
  })

  it('shows skeletons while loading', async () => {
    success()
    let resolve
    api.fetchNearby.mockReturnValue(new Promise(r => { resolve = r }))
    await click(button('Use my location'))
    expect(container.querySelector('[data-testid="nearby-loading"]')).not.toBeNull()
    expect(container.querySelector('[data-testid="nearby-status"]').textContent).toMatch(/Looking for places/)
    await act(async () => { resolve(DATA) })
    expect(container.querySelector('[data-testid="nearby-loading"]')).toBeNull()
  })

  it('explains a denied permission and offers to try again', async () => {
    geo.getCurrentPosition.mockImplementation((_ok, fail) => fail({ code: 1 }))
    await click(button('Use my location'))
    expect(container.querySelector('[role="alert"]').textContent).toMatch(/Location access is turned off/)
    expect(api.fetchNearby).not.toHaveBeenCalled()
    // One "Try again", not two
    expect([...container.querySelectorAll('button')].filter(b => b.textContent.includes('Try again'))).toHaveLength(1)

    success()
    api.fetchNearby.mockResolvedValue(DATA)
    await click(button('Try again'))
    await flush()
    expect(geo.getCurrentPosition).toHaveBeenCalledTimes(2)
    expect(container.textContent).toMatch(/Belém Tower/)
  })

  it('explains a timeout and a browser without geolocation', async () => {
    geo.getCurrentPosition.mockImplementation((_ok, fail) => fail({ code: 3 }))
    await click(button('Use my location'))
    expect(container.textContent).toMatch(/took too long/)

    Object.defineProperty(navigator, 'geolocation', { value: undefined, configurable: true })
    await click(button('Try again'))
    expect(container.textContent).toMatch(/can’t share your location/)
    expect(button('Try again')).toBeUndefined()
  })

  it.each([
    [404, { code: 'no_place', message: 'We don\'t know a town or city near you yet.' }, /town or city near you/],
    [429, 'Too many requests — please wait 40 seconds.', /please wait 40 seconds/],
    [503, { code: 'ai_limit', message: 'AI limit reached for this month — try again on the 1st.' }, /AI limit reached/],
    [503, { code: 'ai_billing', message: 'AI features are unavailable right now.' }, /unavailable right now/],
    [503, { code: 'grounding_unavailable', message: 'Live web and map results need the Gemini provider.' }, /Live map results aren’t available/],
    [502, { code: 'agent_error', message: 'We couldn\'t find things to do nearby. Try again.' }, /couldn't find things to do/],
  ])('shows a friendly error for %i', async (status, detail, text) => {
    success()
    api.fetchNearby.mockRejectedValue({ response: { status, data: { detail } } })
    await click(button('Use my location'))
    await flush()
    const alert = container.querySelector('[role="alert"]')
    expect(alert.textContent).toMatch(text)
    expect(alert.textContent).not.toMatch(/Gemini provider/)
  })

  it('gives up after the watchdog when the browser never answers (dismissed prompt)', async () => {
    vi.useFakeTimers()
    try {
      await click(button('Use my location')) // getCurrentPosition never calls back
      expect(container.textContent).toMatch(/Finding your location/)
      await act(async () => { vi.advanceTimersByTime(GEO_WATCHDOG_MS) })
      expect(container.querySelector('[role="alert"]').textContent).toMatch(/took too long/)
      expect(button('Try again')).toBeDefined()
      // A late answer from the browser is ignored
      const [ok] = geo.getCurrentPosition.mock.calls[0]
      await act(async () => ok({ coords: { latitude: 1, longitude: 2 } }))
      expect(api.fetchNearby).not.toHaveBeenCalled()
    } finally {
      vi.useRealTimers()
    }
  })

  it('can cancel while waiting for the location', async () => {
    await click(button('Use my location'))
    await click(button('Cancel'))
    expect(container.textContent).toMatch(/Use your location\?/)
    const [ok] = geo.getCurrentPosition.mock.calls[0]
    await act(async () => ok({ coords: { latitude: 1, longitude: 2 } }))
    expect(api.fetchNearby).not.toHaveBeenCalled()
  })

  it('does not offer no_place as a plain retry', async () => {
    success()
    api.fetchNearby.mockRejectedValue({ response: { status: 404, data: { detail: { code: 'no_place', message: 'We don\'t know a town or city near you yet.' } } } })
    await click(button('Use my location'))
    await flush()
    expect(button('Try again')).toBeUndefined()
    expect(button('Check again from where you are now')).toBeDefined()
  })

  it('never writes results to storage', async () => {
    const setItem = vi.spyOn(Storage.prototype, 'setItem')
    success()
    api.fetchNearby.mockResolvedValue(DATA)
    await click(button('Use my location'))
    await flush()
    expect(container.textContent).toMatch(/Belém Tower/)
    expect(setItem).not.toHaveBeenCalled()
    expect(localStorage.length).toBe(0)
    expect(sessionStorage.length).toBe(0)
  })
})
