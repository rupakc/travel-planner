// @vitest-environment jsdom
// Where the hotel price-watch button appears: Results hotel cards, Chat hotel
// cards and the Chat My Plan drawer's selected hotel, each with the trip it
// belongs to (the button itself is tested in components/alerts).
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'

vi.mock('../components/alerts/WatchHotelButton', () => ({
  default: ({ hotel, searchData, variant, source }) => (
    <span data-testid="watch-hotel">{`${hotel.name}|${searchData?.departure_date}|${variant || 'inline'}|${source}`}</span>
  ),
}))

import { HotelsSection } from './ResultsPage'
import { ChatHotelsSection, ChatPlanDrawer } from './ChatPage'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const SEARCH = { destination: 'Lisbon', departure_date: '2099-12-10', return_date: '2099-12-14', adults: 2 }
const HOTELS = { results: [{ name: 'Lumen Hotel', price_per_night_usd: 100 }, { name: 'Brown’s', price_per_night_usd: 150 }] }
const sel = { flight: null, flights: [], hotel: null, activities: [], places_to_see: [] }

let container, root
beforeEach(() => {
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => [] })))
})
afterEach(() => {
  act(() => root.unmount())
  container.remove()
  vi.unstubAllGlobals()
})
const render = (el) => act(() => root.render(<MemoryRouter>{el}</MemoryRouter>))
const buttons = () => [...container.querySelectorAll('[data-testid="watch-hotel"]')].map(b => b.textContent)

describe('hotel price-watch entry points', () => {
  it('puts one on every Results hotel card, with the search', () => {
    render(<HotelsSection data={HOTELS} selections={sel} onSelect={() => {}} searchData={SEARCH} />)
    expect(buttons()).toEqual(['Lumen Hotel|2099-12-10|inline|results', 'Brown’s|2099-12-10|inline|results'])
  })

  it('puts one on every Chat hotel card, with the chat’s trip', () => {
    render(<ChatHotelsSection data={HOTELS} selections={sel} onSelect={() => {}} searchContext={SEARCH} />)
    expect(buttons()).toEqual(['Lumen Hotel|2099-12-10|compact|chat', 'Brown’s|2099-12-10|compact|chat'])
  })

  it('puts one on the Chat My Plan drawer’s selected hotel', () => {
    render(<ChatPlanDrawer isOpen onClose={() => {}} searchContext={SEARCH} planName="Lisbon" onPlanNameChange={() => {}}
      onRemoveSelection={() => {}} token="tok" loadedPlanId={null} onLoadPlan={() => {}} onClearLoadedPlan={() => {}}
      onClearSelections={() => {}}
      selections={{ ...sel, hotel: HOTELS.results[0], tips: [], getting_around: [], itinerary_slots: [] }} />)
    expect(buttons()).toEqual(['Lumen Hotel|2099-12-10|inline|chat_plan'])
  })
})
