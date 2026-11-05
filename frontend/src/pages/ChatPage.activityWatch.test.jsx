// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'

const auth = { token: 'tok', user: { username: 'chatter' }, preferences: {} }
vi.mock('../context/AuthContext', () => ({ useAuth: () => auth, useOptionalAuth: () => auth }))
const lookups = []
vi.mock('../context/AlertsContext', () => ({
  useAlerts: () => ({
    caps: { serpapi: true, fareWatch: true, email: false }, watchVersion: 0, watchesChanged: vi.fn(),
    shouldOfferBrowserAlerts: () => false, answerBrowserAlerts: vi.fn(),
  }),
  usePriceWatchFor: (kind, spec) => { lookups.push(spec); return [null, vi.fn()] },
  useWatchFor: () => [null, vi.fn()],
}))
vi.mock('react-leaflet', () => ({
  MapContainer: () => null, TileLayer: () => null, Marker: () => null, Popup: () => null,
  Polyline: () => null, useMap: () => ({}),
}))
vi.mock('../components/TripMap', () => ({ default: () => null }))
vi.mock('../utils/analytics', () => ({ track: vi.fn() }))

import ChatPage from './ChatPage'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

describe('Chat activity rows can be watched', () => {
  let container, root
  beforeEach(() => {
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
    Element.prototype.scrollIntoView = vi.fn()
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => [] })))
    lookups.length = 0
  })
  afterEach(() => {
    act(() => root.unmount())
    container.remove()
    localStorage.clear()
    vi.unstubAllGlobals()
  })

  it('takes the city from the planning message, with no page-level search context', async () => {
    // A specialist answer ("good tours in Lisbon?"): sections + planning_start
    // destination, no search_context event and no saved plan.
    localStorage.setItem('chat_history_chatter', JSON.stringify({
      messages: [
        { role: 'user', content: 'good tours in Lisbon?' },
        {
          role: 'assistant', content: '', planning: true, planningDone: true, planDestination: 'Lisbon',
          sections: { activities: { results: [{ name: 'Belém walking tour', price_usd: 30 }] } },
          sectionStatuses: { activities: 'done' },
        },
      ],
      sessionContext: {},
      lastSearchContext: null,
    }))
    await act(async () => root.render(<MemoryRouter initialEntries={['/chat']}><ChatPage /></MemoryRouter>))
    const watch = [...container.querySelectorAll('button')].find(b => b.textContent.includes('Watch price'))
    expect(watch).toBeDefined()
    expect(lookups.at(-1)).toEqual({ name: 'Belém walking tour', city: 'Lisbon', travellers: 1, estimate_price: 30 })
  })

  it('specialist answers: hotel and activity rows take their trip from the session context the message streamed', async () => {
    localStorage.setItem('chat_history_chatter', JSON.stringify({
      messages: [
        { role: 'user', content: 'hotels and things to do in Lisbon?' },
        {
          role: 'assistant', content: '', planning: true, planningDone: true,
          // no search_context (the backend never emits it) — only the session context update
          tripContext: { destination: 'Lisbon', departure_date: '2099-12-10', return_date: '2099-12-14', num_travelers: 2 },
          sections: {
            hotels: { results: [{ name: 'Lumen Hotel', price_per_night_usd: 100 }] },
            activities: { results: [{ name: 'Tram 28 ride' }] },
          },
          sectionStatuses: { hotels: 'done', activities: 'done' },
        },
      ],
      sessionContext: {},
      lastSearchContext: null,
    }))
    await act(async () => root.render(<MemoryRouter initialEntries={['/chat']}><ChatPage /></MemoryRouter>))
    const watches = [...container.querySelectorAll('button')].filter(b => b.textContent.includes('Watch price'))
    expect(watches.length).toBe(2) // the hotel row and the activity row
    expect(lookups).toContainEqual(expect.objectContaining({ name: 'Lumen Hotel', city: 'Lisbon', check_in: '2099-12-10', check_out: '2099-12-14' }))
    expect(lookups).toContainEqual({ name: 'Tram 28 ride', city: 'Lisbon', travellers: 2 })
  })
})
