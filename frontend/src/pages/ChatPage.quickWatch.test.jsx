// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'

const v2 = vi.hoisted(() => ({ on: true, livePrices: true }))
vi.mock('../hooks/useAlertsV2', () => ({ useAlertsV2: () => v2 }))
vi.mock('../hooks/useAirportCities', () => ({ useAirportCities: () => (c) => c }))
vi.mock('../components/alerts/WatchHotelButton', () => ({ default: () => <span data-testid="classic-hotel" /> }))
vi.mock('../components/alerts/WatchActivityButton', () => ({ default: () => <span data-testid="classic-activity" /> }))
vi.mock('../components/alerts2/QuickWatchButton', () => ({
  default: (p) => <span data-testid="quick" data-kind={p.kind} data-surface={p.surface} data-plan={String(p.planId)}>{p.title}</span>,
}))
vi.mock('../components/alerts2/WatchSuggestions', () => ({ default: (p) => <span data-testid="suggest" data-plan={p.planId} /> }))

import { ChatPlanDrawer } from './ChatPage'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const SEARCH = { destination: 'Lisbon', departure_date: '2099-12-10', return_date: '2099-12-14', adults: 2 }
const sel = {
  flight: null, flights: [], hotel: { name: 'Lumen Hotel', price_per_night_usd: 100 },
  activities: [{ name: 'Belem tour', city: 'Lisbon', price_usd: 30 }],
  places_to_see: [], tips: [], getting_around: [], itinerary_slots: [],
}

let container, root
beforeEach(() => {
  v2.on = true
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  vi.stubGlobal('fetch', vi.fn(async (url, init) => ({ ok: true, json: async () => (init?.method === 'POST' ? { id: 8 } : []) })))
})
afterEach(() => { act(() => root.unmount()); container.remove(); vi.unstubAllGlobals() })
const render = () => act(() => root.render(
  <MemoryRouter>
    <ChatPlanDrawer isOpen onClose={() => {}} selections={sel} searchContext={SEARCH} planName="Lisbon" onPlanNameChange={() => {}}
      onRemoveSelection={() => {}} token="tok" loadedPlanId={null} onLoadPlan={() => {}} onClearLoadedPlan={() => {}}
      onClearSelections={() => {}} />
  </MemoryRouter>,
))
const q = (id) => [...container.querySelectorAll(`[data-testid="${id}"]`)]

describe('Chat one-tap watch', () => {
  it('chat plan section has one-tap', async () => {
    await render()
    expect(q('quick').map((n) => [n.dataset.kind, n.dataset.surface])).toEqual([['hotel', 'chat'], ['activity', 'chat']])
    expect(q('classic-hotel')).toHaveLength(1)
    expect(q('classic-activity')).toHaveLength(1)
  })

  it('flag off: classic buttons only', async () => {
    v2.on = false
    await render()
    expect(q('quick')).toHaveLength(0)
    expect(q('classic-hotel')).toHaveLength(1)
    expect(q('classic-activity')).toHaveLength(1)
  })

  it('offers suggestions after a save', async () => {
    await render()
    const save = [...container.querySelectorAll('button')].find((b) => /Save Plan/i.test(b.textContent))
    await act(async () => { save.click() })
    await act(async () => {})
    expect(q('suggest').map((n) => n.dataset.plan)).toEqual(['8'])
  })
})
