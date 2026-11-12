// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act, useEffect } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'

const journeyState = { enabled: false, tripsApi: true }
const putSnapshot = vi.fn()
const recheckStressTest = vi.fn()
let emit = {}

vi.mock('../components/TripMap', () => ({ default: () => null }))
vi.mock('../utils/analytics', () => ({ track: vi.fn() }))
vi.mock('../hooks/useJourney', () => ({ useJourney: () => journeyState }))
vi.mock('../services/tripsApi', () => ({ putSnapshot: (...a) => putSnapshot(...a) }))
vi.mock('../context/AuthContext', async (orig) => {
  const auth = () => ({ user: { id: 1, username: 'u' }, token: 'tok', logout: () => {} })
  return { ...(await orig()), useAuth: auth, useOptionalAuth: auth }
})
vi.mock('../services/api', async (orig) => ({
  ...(await orig()),
  streamSearch: (sd, onResult, onDone) => { emit = { onResult, onDone }; return () => {} },
  recheckStressTest: (...a) => recheckStressTest(...a),
  getSerpapiConfigured: () => Promise.resolve(false),
  saveRecentSearch: () => Promise.resolve(),
}))

import ResultsPage, { MyPlanDrawer } from './ResultsPage'
import { SearchDataProvider, useSearchData } from '../context/SearchDataContext'
import { removeSlot, itineraryFingerprint } from '../utils/itineraryLayout'
import { snapshotFromResults } from '../utils/tripSnapshot'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const SEL = {
  flight: null, flights: [], hotel: null, activities: [{ name: 'Tower' }], places_to_see: [], walking_tours: [], sim: null,
  tips: [], getting_around: [], events: [], itinerary_slots: [], itinerary_notes: {}, itinerary_edits: {}, itinerary_layout: null,
}
const flush = () => act(async () => { await new Promise((r) => setTimeout(r, 0)) })

let container, root
beforeEach(() => {
  journeyState.enabled = false
  putSnapshot.mockReset().mockResolvedValue(undefined)
  recheckStressTest.mockReset().mockResolvedValue({ overall: 'green', findings: [] })
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})
afterEach(() => {
  act(() => root.unmount())
  container.remove()
  vi.unstubAllGlobals()
})

function mockFetch(postId = 77) {
  const fetchMock = vi.fn(async (url, opts) => {
    if (opts?.method === 'POST' || opts?.method === 'PUT') return { ok: true, json: async () => ({ id: postId }) }
    return { ok: true, json: async () => [] }
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

const drawer = (props = {}) => (
  <MemoryRouter>
    <MyPlanDrawer isOpen onClose={() => {}} selections={SEL} planName="Trip" onPlanNameChange={() => {}}
      onRemoveSelection={() => {}} onViewPlan={() => {}} token="tok" searchData={{ destination: 'Lisbon' }} screenSearchData={{ destination: 'Lisbon' }}
      results={{ visa: { visa_type: 'e-visa', verification: { level: 'verified' } }, forex: { error: 'x' } }}
      loadedPlanId={null} onLoadPlan={() => {}} onClearLoadedPlan={() => {}} onClearSelections={() => {}} {...props} />
  </MemoryRouter>
)
const saveBtn = () => container.querySelector('[data-tid="drawer.save"]')

describe('MyPlanDrawer trip saving', () => {
  it('saves a snapshot with the new id after a save', async () => {
    mockFetch(77)
    act(() => root.render(drawer()))
    await flush()
    expect(saveBtn()).not.toBeNull()
    await act(async () => { saveBtn().click() })
    await flush()
    expect(putSnapshot).toHaveBeenCalledTimes(1)
    const [token, id, snap] = putSnapshot.mock.calls[0]
    expect([token, id]).toEqual(['tok', 77])
    expect(snap.visa).toEqual({ visa_type: 'e-visa' })
    expect(snap).toEqual({ visa: { visa_type: 'e-visa' } })
    expect('forex' in snap).toBe(false)
  })

  it('skips the snapshot call when every section is empty', async () => {
    mockFetch()
    act(() => root.render(drawer({ results: { forex: { error: 'x' } } })))
    await flush()
    await act(async () => { saveBtn().click() })
    await flush()
    expect(putSnapshot).not.toHaveBeenCalled()
  })

  it('does not snapshot on update when the on-screen search is another trip', async () => {
    mockFetch()
    act(() => root.render(drawer({ loadedPlanId: 5, screenSearchData: { destination: 'Porto' } })))
    await flush()
    await act(async () => { saveBtn().click() })
    await flush()
    expect(putSnapshot).not.toHaveBeenCalled()
  })

  it('uses loadedPlanId on update', async () => {
    mockFetch()
    act(() => root.render(drawer({ loadedPlanId: 5, screenSearchData: { destination: 'Lisbon' } })))
    await flush()
    await act(async () => { saveBtn().click() })
    await flush()
    expect(putSnapshot.mock.calls[0][1]).toBe(5)
  })

  it('shows no error when the snapshot call is rejected', async () => {
    mockFetch()
    putSnapshot.mockRejectedValue(new Error('404'))
    act(() => root.render(drawer()))
    await flush()
    await act(async () => { saveBtn().click() })
    await flush()
    expect(container.textContent).toContain('Plan saved!')
    expect(container.textContent).not.toContain('Save failed')
  })

  it('shows "Open trip" only with the journey on', async () => {
    mockFetch(77)
    act(() => root.render(drawer()))
    await flush()
    await act(async () => { saveBtn().click() })
    await flush()
    expect(container.querySelector('[data-tid="drawer.open-trip"]')).toBeNull()
    act(() => root.unmount()); root = createRoot(container)
    journeyState.enabled = true
    act(() => root.render(drawer()))
    await flush()
    await act(async () => { saveBtn().click() })
    await flush()
    const link = container.querySelector('[data-tid="drawer.open-trip"]')
    expect(link.getAttribute('href')).toBe('/trips/77')
    expect(link.textContent).toBe('Open trip')
  })

  it('has the teal header, no slate-500', async () => {
    mockFetch()
    act(() => root.render(drawer()))
    await flush()
    expect(container.innerHTML).not.toContain('slate-500')
    expect(container.innerHTML).toContain('from-teal-700 to-teal-800')
  })
})

describe('ResultsPage with a pending plan', () => {
  const ITIN = { days: [{ day_number: 1, slots: [{ time_of_day: 'morning', activity: 'Tower' }, { time_of_day: 'afternoon', activity: 'Lunch' }] }] }
  const SD = { destination: 'Lisbon', departure_date: '2027-04-01', return_date: '2027-04-08', origin: 'NYC', interests: [] }
  const layout = { ...removeSlot(ITIN, null, '1-afternoon'), fingerprint: itineraryFingerprint(ITIN) }
  const PLAN = { id: 9, name: 'Saved', search_data: SD, selections: { ...SEL, itinerary_layout: layout } }

  function Starter() {
    const { setPendingSearchData, setPendingPlan } = useSearchData()
    useEffect(() => { setPendingPlan(PLAN); setPendingSearchData(SD) }, [])
    return null
  }

  it('loads the plan once the search starts, then clears it; re-check carries plan_id', async () => {
    mockFetch()
    act(() => root.render(
      <MemoryRouter><SearchDataProvider><Starter /><ResultsPage /></SearchDataProvider></MemoryRouter>,
    ))
    await act(async () => { await new Promise((r) => setTimeout(r, 120)) })
    act(() => { emit.onResult('itinerary', ITIN); emit.onResult('stress_test', { overall: 'amber', findings: [] }); emit.onDone() })
    await flush()
    expect(container.textContent).toContain('Editing saved')
    const btn = [...container.querySelectorAll('button')].find((b) => /Re-check my edited plan/.test(b.textContent))
    expect(btn).toBeTruthy()
    await act(async () => { btn.click() })
    expect(recheckStressTest).toHaveBeenCalledTimes(1)
    expect(recheckStressTest.mock.calls[0][0].plan_id).toBe(9)
  })
})

describe('snapshot shape', () => {
  it('is the five keys', () => {
    expect(Object.keys(snapshotFromResults({})).sort()).toEqual(['emergency_card', 'forex', 'packing_list', 'visa', 'weather'])
  })
})
