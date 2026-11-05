// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'

const auth = { token: 'tok', user: { username: 'u' }, preferences: {} }
vi.mock('../context/AuthContext', () => ({ useAuth: () => auth, useOptionalAuth: () => auth }))
const alerts = {
  caps: { serpapi: true, fareWatch: true, email: false }, watchVersion: 0, watchesChanged: vi.fn(),
  priceWatchFor: vi.fn(async () => null), shouldOfferBrowserAlerts: () => false, answerBrowserAlerts: vi.fn(),
}
vi.mock('../context/AlertsContext', () => ({
  useAlerts: () => alerts,
  usePriceWatchFor: () => [null, vi.fn()],
}))
vi.mock('../components/TripMap', () => ({ default: () => null }))
vi.mock('../utils/analytics', () => ({ track: vi.fn() }))

import { ActivitiesSection } from './ResultsPage'
import { ActivityTripContext } from '../components/alerts/activityTripContext'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

describe('Watch price on activity cards', () => {
  let container, root
  beforeEach(() => {
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
  })
  afterEach(() => {
    act(() => root.unmount())
    container.remove()
    document.body.innerHTML = ''
  })

  it('shows on each card and opens the watch dialog without selecting the card', async () => {
    const onSelect = vi.fn()
    await act(async () => root.render(
      <MemoryRouter>
        <ActivityTripContext.Provider value={{ searchData: { destination: 'Lisbon', num_travelers: 2 }, itinerary: null }}>
          <ActivitiesSection data={{ results: [{ name: 'Belém walking tour', category: 'history', price_usd: 30 }] }}
            selections={{ activities: [] }} onSelect={onSelect} />
        </ActivityTripContext.Provider>
      </MemoryRouter>,
    ))
    const watch = [...container.querySelectorAll('button')].find(b => b.textContent.includes('Watch price'))
    expect(watch.getAttribute('aria-label')).toBe('Watch the price of Belém walking tour')
    await act(async () => watch.click())
    expect(onSelect).not.toHaveBeenCalled()
    expect(document.querySelector('[role="dialog"]').textContent).toContain('Watch this activity')
  })
})
