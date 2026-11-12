// @vitest-environment jsdom
// Phase 4 entry points: new share dialog with features.sharing, the old flow without it.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'

let mockConfig = {}
vi.mock('../../hooks/useClientConfig', () => ({
  useClientConfig: () => ({ config: mockConfig, loaded: true }),
  featureOn: (c, n) => c?.features?.[n] === true,
}))
vi.mock('./ShareDialog', () => ({
  default: ({ kind, planId, onClose }) => (
    <div data-testid="share-dialog" data-kind={kind} data-plan={String(planId ?? '')}>
      <button data-testid="dlg-close" onClick={onClose} />
    </div>
  ),
}))
vi.mock('../../context/AuthContext', async (orig) => ({ ...(await orig()), useAuth: () => ({ token: 'tok' }), useOptionalAuth: () => ({ token: 'tok' }) }))
vi.mock('../../services/alertsApi', () => ({ getSavings: vi.fn() }))
vi.mock('../../hooks/useJourney', () => ({ useJourney: () => ({ enabled: true, loaded: true }) }))
vi.mock('../../services/tripsApi', () => ({ getRecap: vi.fn(), completeRecap: vi.fn() }))
vi.mock('../../services/api', async (orig) => ({ ...(await orig()), sharePlan: vi.fn() }))
vi.mock('../../game/announce', () => ({ announceGame: vi.fn() }))
vi.mock('../../telemetry/client', () => ({ emit: vi.fn() }))
vi.mock('../trips/RecapMap', () => ({ default: () => <div /> }))

import { ChatPlanDrawer } from '../../pages/ChatPage'
import { MyPlanDrawer } from '../../pages/ResultsPage'
import Recap from '../trips/Recap'
import SavingsTally from '../alerts2/SavingsTally'
import { getRecap } from '../../services/tripsApi'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const ON = { features: { sharing: 1 } }
const PLAN = { id: 7, name: 'Lisbon', created_at: '2026-11-01', selections: {}, search_data: {} }
const SEL = { flight: null, flights: [], hotel: null, activities: [], places_to_see: [], sim: null, tips: [], getting_around: [], events: [], walking_tours: [], itinerary_slots: [], itinerary_notes: {}, itinerary_edits: {} }
const RECAP = { trip_id: 12, title: 'Lisbon', days: 8, nights: 7, places: [], visited_count: 9, rated_count: 7, route: [], distance_km: 0, countries: [], continents: [], spend: null, journal_count: 0, checkin_days: 0, completed_at: null, can_complete: true }
const SAV = { total_usd: 245, by_currency: {}, drops_caught: 4, targets_hit: 1, watches_active: 6, milestones: [50, 200, 1000], next_milestone: 1000, progress_pct: 24 }

let container, root
const tid = (id) => container.querySelector(`[data-tid="${id}"]`)
const dialog = () => container.querySelector('[data-testid="share-dialog"]')
const flush = () => act(async () => { await new Promise((r) => setTimeout(r, 0)) })
const render = async (el) => { await act(async () => root.render(<MemoryRouter>{el}</MemoryRouter>)); await flush() }
const click = async (el) => { await act(async () => { el.click() }); await flush() }

beforeEach(() => {
  mockConfig = {}
  window.matchMedia = vi.fn(() => ({ matches: true, addEventListener() {}, removeEventListener() {} }))
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => [PLAN] })))
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container)
})
afterEach(() => { act(() => root.unmount()); container.remove(); vi.unstubAllGlobals() })

const chat = () => render(<ChatPlanDrawer isOpen onClose={() => {}} searchContext={{}} planName="L" onPlanNameChange={() => {}}
  onRemoveSelection={() => {}} token="tok" loadedPlanId={null} onLoadPlan={() => {}} onClearLoadedPlan={() => {}}
  onClearSelections={() => {}} selections={SEL} />)
const results = () => render(<MyPlanDrawer isOpen onClose={() => {}} selections={SEL} planName="L" onPlanNameChange={() => {}}
  onRemoveSelection={() => {}} onViewPlan={() => {}} token="tok" searchData={{}} results={{}} loadedPlanId={null}
  onLoadPlan={() => {}} onClearLoadedPlan={() => {}} onClearSelections={() => {}} />)

describe('Chat plan drawer', () => {
  it('flag on: opens the plan dialog, no inline share', async () => {
    mockConfig = ON; await chat()
    expect(tid('chat.plan-share')).toBeNull()
    await click(tid('chat.plan-share-link'))
    expect(dialog().dataset).toMatchObject({ kind: 'plan', plan: '7' })
  })
  it('flag off: old inline share, no dialog', async () => {
    await chat()
    expect(tid('chat.plan-share-link')).toBeNull()
    await click(tid('chat.plan-share'))
    expect(dialog()).toBeNull()
    expect(fetch.mock.calls.some(([u]) => u === '/api/plans/7/share')).toBe(true)
  })
})

describe('Results plan drawer', () => {
  it('flag on: opens the plan dialog', async () => {
    mockConfig = ON; await results()
    expect(tid('drawer.share-plan')).toBeNull()
    await click(tid('drawer.share-link'))
    expect(dialog().dataset).toMatchObject({ kind: 'plan', plan: '7' })
    await click(container.querySelector('[data-testid="dlg-close"]'))
    expect(dialog()).toBeNull()
  })
  it('flag off: old inline share', async () => {
    await results()
    expect(tid('drawer.share-link')).toBeNull()
    await click(tid('drawer.share-plan'))
    expect(dialog()).toBeNull()
    expect(fetch.mock.calls.some(([u]) => u === '/api/plans/7/share')).toBe(true)
  })
})

describe('Recap', () => {
  const recap = async () => { getRecap.mockResolvedValue(RECAP); await render(<Recap trip={{ id: 12, destination: 'Lisbon' }} token="tok" />) }
  it('flag on: dialog kind recap with the trip id', async () => {
    mockConfig = ON; await recap()
    expect(tid('recap.share')).toBeNull()
    await click(tid('recap.share-link'))
    expect(dialog().dataset).toMatchObject({ kind: 'recap', plan: '12' })
  })
  it('flag off: old share button only', async () => {
    await recap()
    expect(tid('recap.share')).not.toBeNull()
    expect(tid('recap.share-link')).toBeNull()
  })
})

describe('Savings tally', () => {
  it('flag on: adds a Share link button (kind savings) beside the card button', async () => {
    mockConfig = ON; await render(<SavingsTally savings={SAV} />)
    expect(tid('savings-share')).not.toBeNull()
    await click(tid('savings-share-link'))
    expect(dialog().dataset.kind).toBe('savings')
  })
  it('flag off: only the existing card button', async () => {
    await render(<SavingsTally savings={SAV} />)
    expect(tid('savings-share')).not.toBeNull()
    expect(tid('savings-share-link')).toBeNull()
  })
})
