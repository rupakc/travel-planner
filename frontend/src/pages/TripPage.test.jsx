// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom'

const journey = vi.hoisted(() => ({ value: { enabled: true, tripsApi: true, offlinePack: true, loaded: true } }))
const pack = vi.hoisted(() => ({ value: { pack: null, savedAt: null, loading: false } }))
const search = vi.hoisted(() => ({
  setPendingPlan: vi.fn(), setPendingSearchData: vi.fn(), showResults: vi.fn(),
}))

vi.mock('../hooks/useJourney', () => ({ useJourney: () => journey.value }))
vi.mock('../context/AuthContext', () => ({ useAuth: () => ({ token: 'tok', user: { id: 7, username: 'rupak' } }) }))
vi.mock('../context/SearchDataContext', () => ({ useSearchData: () => search }))
vi.mock('../telemetry/client', () => ({ emit: vi.fn() }))
vi.mock('../offline/useOfflinePack', () => ({ useOfflinePack: vi.fn(() => pack.value) }))
vi.mock('../offline/useOnline', () => ({ useOnline: () => true }))
vi.mock('../services/tripsApi', () => ({
  getTrip: vi.fn(), patchTrip: vi.fn(), deleteTrip: vi.fn(), notifyTripsChanged: vi.fn(),
  getPrep: vi.fn(async () => ({ items: [{ id: 'visa', status: 'done' }] })),
}))
const { tabProps, stub } = vi.hoisted(() => {
  const tabProps = { last: null }
  const stub = (name) => ({
    default: (props) => { tabProps.last = props; return <div data-testid={name}>{props.trip?.title}</div> },
  })
  return { tabProps, stub }
})
vi.mock('../components/trips/PrepChecklist', () => stub('prep'))
vi.mock('../components/trips/TodayView', () => stub('today'))
vi.mock('../components/trips/ExpenseLog', () => stub('money'))
vi.mock('../components/trips/Journal', () => stub('journal'))
vi.mock('../components/trips/Recap', () => stub('recap'))
vi.mock('../components/trips/OfflinePack', () => stub('offline'))
vi.mock('../components/trips/CompletenessMeter', () => ({
  default: (props) => <div data-testid="completeness" data-surface={props.surface} data-visa={String(props.visaChecked)} />,
}))
vi.mock('../components/PlanViewModal', () => ({
  default: (props) => (
    <div data-testid="plan-view" data-inline={String(!!props.inline)}>
      {props.plan?.name}
      <button type="button" data-tid="test.planSave"
        onClick={() => props.onSaved?.({ ...props.plan, selections: { hotel: { name: 'Hotel Novo' } } })}>save</button>
    </div>
  ),
}))

import { emit } from '../telemetry/client'
import { useOfflinePack } from '../offline/useOfflinePack'
import { getTrip, patchTrip, deleteTrip, notifyTripsChanged } from '../services/tripsApi'
import TripPage from './TripPage'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
let container, root, location

const TRIP = {
  id: 3, title: 'Lisbon in spring', destination: 'Lisbon', destinations: ['Lisbon'], origin: 'NYC',
  start_date: '2027-04-01', end_date: '2027-04-08', nights: 7,
  phase: 'planning', phase_source: 'auto', days_to_start: 140, day_index: null,
  num_travelers: 2, budget_usd: 3000, countries: ['PT'],
  prep: { done: 0, total: 9, percent: 0, complete: false }, has_itinerary: true,
  recap_completed_at: null, created_at: '2026-11-01T00:00:00Z', updated_at: '2026-11-01T00:00:00Z',
}
const ON_ROAD = { ...TRIP, phase: 'on_the_road', days_to_start: null, day_index: 3 }
const PLAN = {
  id: 3, name: 'Lisbon in spring',
  search_data: { origin: 'NYC', destination: 'Lisbon', departure_date: '2027-04-01', return_date: '2027-04-08' },
  selections: { hotel: { name: 'Casa Azul' } },
}

// A local 'YYYY-MM-DD' `n` days from today (the pack's phase follows this device's date).
function shiftDay(n) {
  const d = new Date()
  d.setDate(d.getDate() + n)
  return [d.getFullYear(), String(d.getMonth() + 1).padStart(2, '0'), String(d.getDate()).padStart(2, '0')].join('-')
}

function Probe() {
  location = useLocation()
  return null
}

function tripRoute(path) {
  const m = /^\/trips\/(\d+)(?:\/([a-z]+))?/.exec(path)
  return m ? { id: Number(m[1]), tab: m[2] ?? null } : null
}

function Screen() {
  const loc = useLocation()
  const trip = tripRoute(loc.pathname)
  return trip ? <TripPage tripId={trip.id} tab={trip.tab} /> : null
}

async function render(path) {
  await act(async () => root.render(
    <MemoryRouter initialEntries={[path]}>
      <Routes><Route path="*" element={<><Screen /><Probe /></>} /></Routes>
    </MemoryRouter>,
  ))
  await act(async () => {})
}

const tid = (id) => container.querySelector(`[data-tid="${id}"]`)
const testid = (id) => container.querySelector(`[data-testid="${id}"]`)
const click = async (el) => { await act(async () => el.click()) }

beforeEach(() => {
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  journey.value = { enabled: true, tripsApi: true, offlinePack: true, loaded: true }
  pack.value = { pack: null, savedAt: null, loading: false }
  globalThis.fetch = vi.fn(async () => ({ ok: true, json: async () => PLAN }))
})
afterEach(() => {
  act(() => root.unmount())
  container.remove()
  vi.clearAllMocks()
})

describe('TripPage', () => {
  it('renders nothing with the journey off', async () => {
    journey.value = { enabled: false, tripsApi: true, offlinePack: true, loaded: true }
    getTrip.mockResolvedValue(TRIP)
    await render('/trips/3')
    expect(container.innerHTML).toBe('')
    expect(getTrip).not.toHaveBeenCalled()
  })

  it('/trips/3 in on_the_road opens Today', async () => {
    getTrip.mockResolvedValue(ON_ROAD)
    await render('/trips/3')
    expect(getTrip).toHaveBeenCalledWith('tok', 3)
    expect(testid('today')).not.toBeNull()
    expect(tid('trip.tab.today').getAttribute('aria-selected')).toBe('true')
    const tabs = [...container.querySelectorAll('[role="tab"]')].map((b) => b.dataset.tid)
    expect(tabs).toEqual(['trip.tab.today', 'trip.tab.offline', 'trip.tab.money', 'trip.tab.journal', 'trip.tab.overview'])
    expect(tid('trip.header').textContent).toContain('Day 3 of 8')
    expect(emit).toHaveBeenCalledWith('trip_view', { surface: 'today', phase: 'on_the_road' })
  })

  it('tabs get the Trip merged with the plan selections and search_data, and the token (R26)', async () => {
    getTrip.mockResolvedValue(ON_ROAD)
    await render('/trips/3')
    expect(tabProps.last.token).toBe('tok')
    expect(tabProps.last.trip).toEqual({ ...ON_ROAD, selections: PLAN.selections, search_data: PLAN.search_data })
  })

  it('a tab click goes to its URL', async () => {
    getTrip.mockResolvedValue(ON_ROAD)
    await render('/trips/3')
    await click(tid('trip.tab.journal'))
    expect(location.pathname).toBe('/trips/3/journal')
    expect(testid('journal')).not.toBeNull()
  })

  it('a Planning trip shows the countdown and the overview', async () => {
    getTrip.mockResolvedValue(TRIP)
    await render('/trips/3')
    expect(tid('trip.header').textContent).toContain('in 140 days')
    expect(testid('completeness').dataset.surface).toBe('trip')
    expect(testid('completeness').dataset.visa).toBe('true')
    expect(testid('plan-view').dataset.inline).toBe('true')
    expect(globalThis.fetch).toHaveBeenCalledWith('/api/plans/3', expect.objectContaining({
      headers: expect.objectContaining({ Authorization: 'Bearer tok' }),
    }))
  })

  it('a PhaseMenu override calls patchTrip({phase}), and "Follow my dates" calls {phase: null}', async () => {
    getTrip.mockResolvedValue(TRIP)
    patchTrip.mockResolvedValueOnce({ ...TRIP, phase: 'ready', phase_source: 'manual' })
    await render('/trips/3')
    await click(tid('trip.phase'))
    await click(tid('trip.phaseMenu.ready'))
    expect(patchTrip).toHaveBeenCalledWith('tok', 3, { phase: 'ready' })
    expect(emit).toHaveBeenCalledWith('trip_action', { action: 'phase_override' })
    expect(tid('trip.phase').textContent).toContain('Ready')

    patchTrip.mockResolvedValueOnce(TRIP)
    await click(tid('trip.phase'))
    await click(tid('trip.phaseMenu.follow'))
    expect(patchTrip).toHaveBeenLastCalledWith('tok', 3, { phase: null })
    expect(emit).toHaveBeenCalledWith('trip_action', { action: 'phase_clear' })
    expect(tid('trip.phase').textContent).toContain('Planning')
    expect(notifyTripsChanged).toHaveBeenCalledTimes(2)
  })

  it('Escape closes the phase menu and puts focus back on the chip', async () => {
    getTrip.mockResolvedValue(TRIP)
    await render('/trips/3')
    await click(tid('trip.phase'))
    expect(document.activeElement).toBe(tid('trip.phaseMenu.planning'))
    await act(async () => {
      tid('trip.phaseMenu').dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    })
    expect(tid('trip.phaseMenu')).toBeNull()
    expect(document.activeElement).toBe(tid('trip.phase'))
  })

  it('while the plan loads, other tabs get planStatus "loading" and a shared loading strip', async () => {
    getTrip.mockResolvedValue(ON_ROAD)
    globalThis.fetch = vi.fn(() => new Promise(() => {}))
    await render('/trips/3')
    expect(tid('trip.planLoading')).not.toBeNull()
    expect(tabProps.last.planStatus).toBe('loading')
    expect(typeof tabProps.last.onRetryPlan).toBe('function')
  })

  it('a failed plan load shows the shared error strip; Retry loads it into the tabs', async () => {
    getTrip.mockResolvedValue(ON_ROAD)
    globalThis.fetch = vi.fn(async () => ({ ok: false, status: 500, json: async () => ({}) }))
    await render('/trips/3')
    expect(tid('trip.planError')).not.toBeNull()
    expect(tabProps.last.planStatus).toBe('error')
    globalThis.fetch = vi.fn(async () => ({ ok: true, json: async () => PLAN }))
    await click(tid('trip.planRetry'))
    expect(tid('trip.planError')).toBeNull()
    expect(tabProps.last.planStatus).toBe('ready')
    expect(tabProps.last.trip.selections).toEqual(PLAN.selections)
  })

  it('a save in the inline plan updates the selections every tab reads', async () => {
    getTrip.mockResolvedValue(TRIP)
    await render('/trips/3')
    await click(tid('test.planSave'))
    await click(tid('trip.tab.money'))
    expect(tabProps.last.trip.selections).toEqual({ hotel: { name: 'Hotel Novo' } })
    await click(tid('trip.tab.overview'))
    await click(tid('trip.openPlanner'))
    expect(search.setPendingPlan).toHaveBeenCalledWith({ ...PLAN, selections: { hotel: { name: 'Hotel Novo' } } })
  })

  it('renames the trip inline', async () => {
    getTrip.mockResolvedValue(TRIP)
    patchTrip.mockResolvedValueOnce({ ...TRIP, title: 'Porto too' })
    await render('/trips/3')
    await click(tid('trip.rename'))
    const input = tid('trip.titleInput')
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set
      setter.call(input, 'Porto too')
      input.dispatchEvent(new Event('input', { bubbles: true }))
    })
    await act(async () => input.form.requestSubmit())
    expect(patchTrip).toHaveBeenCalledWith('tok', 3, { title: 'Porto too' })
    expect(tid('trip.header').textContent).toContain('Porto too')
  })

  it('deletes the trip, tells the hub, and goes back to Trips', async () => {
    getTrip.mockResolvedValue(TRIP)
    deleteTrip.mockResolvedValueOnce(undefined)
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    await render('/trips/3')
    await click(tid('trip.delete'))
    expect(deleteTrip).toHaveBeenCalledWith('tok', 3)
    expect(notifyTripsChanged).toHaveBeenCalled()
    expect(location.pathname).toBe('/trips')
    window.confirm.mockRestore()
  })

  it('"Open in planner" sets the pending plan and search, shows results and goes to Explore', async () => {
    getTrip.mockResolvedValue(TRIP)
    await render('/trips/3')
    await click(tid('trip.openPlanner'))
    expect(search.setPendingPlan).toHaveBeenCalledWith(PLAN)
    expect(search.setPendingSearchData).toHaveBeenCalledWith(PLAN.search_data)
    expect(search.showResults).toHaveBeenCalled()
    expect(location.pathname).toBe('/explore')
    expect(emit).toHaveBeenCalledWith('trip_action', { action: 'open_planner' })
  })

  it('a Dreaming trip with no search offers "Plan it" with the destination', async () => {
    const dreaming = { ...TRIP, phase: 'dreaming', start_date: null, end_date: null, nights: null, days_to_start: null }
    getTrip.mockResolvedValue(dreaming)
    globalThis.fetch = vi.fn(async () => ({ ok: true, json: async () => ({ id: 3, name: 'Lisbon', search_data: { destination: 'Lisbon' }, selections: {} }) }))
    await render('/trips/3')
    expect(testid('plan-view')).toBeNull()
    expect(tid('trip.openPlanner')).toBeNull()
    await click(tid('trip.planIt'))
    expect(location.pathname).toBe('/explore')
    expect(location.state).toEqual({ prefill: { destination: 'Lisbon' } })
    expect(search.setPendingPlan).not.toHaveBeenCalled()
  })

  it('offline with a pack: the header comes from the pack and only Today and Offline are enabled', async () => {
    getTrip.mockRejectedValue({ status: 0, code: 'network', detail: '' })
    pack.value = {
      pack: { version: 1, trip_id: 3, title: 'Saved Lisbon', start_date: shiftDay(-2), end_date: shiftDay(5), destinations: [],
        selections: { hotel: { name: 'Pack hotel' } } },
      savedAt: '2027-03-30T10:00:00Z', loading: false,
    }
    await render('/trips/3/money')
    expect(useOfflinePack).toHaveBeenCalledWith(7, 3)
    expect(tid('trip.header').textContent).toContain('Saved Lisbon')
    expect(tid('trip.header').textContent).toContain('Day 3 of 8')
    expect(tid('trip.offlineNote')).not.toBeNull()
    const enabled = [...container.querySelectorAll('[role="tab"]')].filter((b) => !b.disabled).map((b) => b.dataset.tid)
    expect(enabled.sort()).toEqual(['trip.tab.offline', 'trip.tab.today'])
    expect(tid('trip.tab.money').disabled).toBe(true)
    expect(testid('money')).toBeNull()
    expect(testid('offline').textContent).toBe('Saved Lisbon')
    expect(tid('trip.rename')).toBeNull()
    expect(tid('trip.delete')).toBeNull()
    expect(tabProps.last.trip.selections).toEqual({ hotel: { name: 'Pack hotel' } })
    expect('search_data' in tabProps.last.trip).toBe(false)
  })

  it('offline without a pack says so and offers Retry', async () => {
    getTrip.mockRejectedValueOnce({ status: 0, code: 'network', detail: '' })
    await render('/trips/3')
    expect(tid('trip.offlineEmpty')).not.toBeNull()
    getTrip.mockResolvedValueOnce(TRIP)
    await click(tid('trip.retry'))
    expect(tid('trip.header').textContent).toContain('Lisbon in spring')
  })

  it('a trip that is not yours shows not found', async () => {
    getTrip.mockRejectedValue({ status: 404, code: 'trip_not_found', detail: '' })
    await render('/trips/3')
    expect(tid('trip.notFound').textContent).toContain("That trip doesn't exist or isn't yours.")
  })
})
