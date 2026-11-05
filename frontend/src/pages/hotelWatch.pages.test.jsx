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

import { HotelsSection, MyPlanDrawer } from './ResultsPage'
import { ChatBubble, ChatHotelsSection, ChatPlanDrawer, withSearchContext } from './ChatPage'

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

  it('puts one on the Results My Plan drawer’s selected hotel', () => {
    render(<MyPlanDrawer isOpen onClose={() => {}} selections={{ ...sel, hotel: HOTELS.results[0], sim: null, tips: [], getting_around: [], events: [], walking_tours: [], itinerary_slots: [], itinerary_notes: {}, itinerary_edits: {} }}
      planName="Lisbon" onPlanNameChange={() => {}} onRemoveSelection={() => {}} onViewPlan={() => {}} token="tok"
      searchData={SEARCH} results={{}} loadedPlanId={null} onLoadPlan={() => {}} onClearLoadedPlan={() => {}} onClearSelections={() => {}} />)
    expect(buttons()).toEqual(['Lumen Hotel|2099-12-10|inline|my_plan'])
  })

  it('dates each chat planning message’s hotels from that message’s own search', () => {
    const planning = (dep, ret, destination) => ({
      role: 'assistant', content: '', planning: true, planningDone: true,
      sections: { hotels: HOTELS }, sectionStatuses: { hotels: 'done' },
      searchContext: { destination, departure_date: dep, return_date: ret, adults: 2 },
    })
    render(<>
      <ChatBubble message={planning('2099-12-10', '2099-12-14', 'Lisbon')} selections={sel} onSelect={() => {}} />
      <ChatBubble message={planning('2100-01-05', '2100-01-12', 'Tokyo')} selections={sel} onSelect={() => {}} />
    </>)
    expect(buttons()).toEqual([
      'Lumen Hotel|2099-12-10|compact|chat', 'Brown’s|2099-12-10|compact|chat',
      'Lumen Hotel|2100-01-05|compact|chat', 'Brown’s|2100-01-05|compact|chat',
    ])
  })

  it('gives restored messages without their own search no dates', () => {
    render(<ChatBubble message={{ role: 'assistant', content: '', planning: true, sections: { hotels: HOTELS }, sectionStatuses: {} }}
      selections={sel} onSelect={() => {}} />)
    expect(buttons()).toEqual(['Lumen Hotel|undefined|compact|chat', 'Brown’s|undefined|compact|chat'])
  })

  it('stores a search_context on the assistant message it belongs to', () => {
    const msgs = [{ role: 'user', content: 'Lisbon' }, { role: 'assistant', content: '' }]
    const out = withSearchContext(msgs, 1, SEARCH)
    expect(out[1].searchContext).toEqual(SEARCH)
    expect(msgs[1].searchContext).toBeUndefined()
    expect(out[0]).toBe(msgs[0])
  })
})
