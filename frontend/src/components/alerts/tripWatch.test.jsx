// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom'

const auth = { token: 'tok', user: { username: 'u', email: 'u@example.com' }, preferences: { nationality: 'German' } }
vi.mock('../../context/AuthContext', () => ({ useAuth: () => auth, useOptionalAuth: () => auth }))

const alerts = {
  caps: { serpapi: true, fareWatch: true, email: true },
  watchesChanged: vi.fn(), shouldOfferBrowserAlerts: vi.fn(() => false), answerBrowserAlerts: vi.fn(),
}
let matched = null
const setMatched = vi.fn()
vi.mock('../../context/AlertsContext', () => ({
  useAlerts: () => alerts,
  usePriceWatchFor: (kind, spec) => { alerts.lastMatch = { kind, spec }; return [matched, setMatched] },
}))
const pending = vi.fn()
vi.mock('../../context/SearchDataContext', () => ({ useSearchData: () => ({ setPendingSearchData: pending }) }))
vi.mock('../../services/api', () => ({ createPriceWatch: vi.fn() }))
vi.mock('../../utils/analytics', () => ({ track: vi.fn() }))

import * as api from '../../services/api'
import TripDialogBody from './dialogs/TripDialogBody'
import TripWatchCard from './cards/TripWatchCard'
import WatchTripButton from './WatchTripButton'
import { PRICE_CARDS, cardFor } from './cards'
import { DIALOG_BODIES, dialogBodyFor } from './dialogs'
import { alertKindFor, kindOf } from './alertKinds'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const FLIGHT = {
  id: 'flight', type: 'flight', group: 'flights', label: 'Flights', live: true, price: 542, currency: 'USD',
  in_total: true, source: 'google_flights', status: 'ok', previous_price: 612, delta: -70,
  subject: { origin_label: 'Berlin', destination_label: 'Lisbon', departure_date: '2099-12-10', return_date: '2099-12-14', num_travelers: 2 },
}
const TOUR_LIVE = {
  id: 'activity-1', type: 'activity', group: 'activities', label: 'Belém walk', live: true, price: 45.74, currency: 'USD',
  in_total: true, source: 'getyourguide_via_google', status: 'ok', detail: 'from $22.87 per person × 2', unit: 'per person',
}
const HOTEL = {
  id: 'hotel', type: 'hotel', group: 'stay', label: 'Lumen Hotel', live: true, price: 356, currency: 'USD',
  in_total: true, source: 'google_hotels', status: 'ok', previous_price: 398, delta: -42,
}
const TOUR = {
  id: 'activity-0', type: 'activity', group: 'activities', label: 'Fado night', live: false, price: 24,
  currency: 'EUR', in_total: false, source: 'getyourguide_via_google', status: 'estimate',
}
const SIM = {
  id: 'sim', type: 'other', group: 'other', label: 'SIM / eSIM', live: false, price: 13, currency: 'USD',
  in_total: true, source: 'ai_estimate', status: 'estimate',
}
const strip = ({ subject, ...c }) => c
const TRIP = {
  id: 9, kind: 'trip', status: 'active', title: 'Lisbon escape', subtitle: 'Lisbon · 10–14 Dec · 2 travellers',
  baseline_price: 1023, last_price: 911, lowest_price: 911, alert_mode: 'any_drop', target_price: null,
  email_enabled: false, check_count: 2, expires_on: '2099-12-10', currency: 'USD', link: null, plan_id: 3,
  subject: { plan_id: 3, city: 'Lisbon', components: [FLIGHT, { ...HOTEL, price: 398 }, TOUR, SIM] },
  last_observation: { status: 'ok', breakdown: [strip(FLIGHT), HOTEL, TOUR, SIM, TOUR_LIVE] },
  history: [{ price: 1023 }, { price: 911 }],
}
const PLAN = {
  id: 3, name: 'Lisbon escape',
  search_data: { origin: 'Berlin', destination: 'Lisbon', departure_date: '2099-12-10', return_date: '2099-12-14', num_travelers: 2 },
  selections: { flight: { price_usd: 612 }, hotel: { name: 'Lumen Hotel', total_price_usd: 398 }, sim: { price_usd: 13 } },
}

let container, root, location
function Where() { location = useLocation(); return null }
const render = async (el, path = '/') => {
  await act(async () => root.render(
    <MemoryRouter initialEntries={[path]}>
      <Routes><Route path="*" element={<>{el}<Where /></>} /></Routes>
    </MemoryRouter>,
  ))
}
const button = (text, scope = document.body) => [...scope.querySelectorAll('button')].find(b => b.textContent.includes(text))

beforeEach(() => {
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  matched = null
  setMatched.mockReset()
  pending.mockReset()
  api.createPriceWatch.mockReset()
  auth.token = 'tok'
  alerts.caps = { serpapi: true, fareWatch: true, email: true }
})
afterEach(() => {
  act(() => root.unmount())
  container.remove()
  document.body.innerHTML = ''
})

describe('registries', () => {
  it('render trip watches with the trip card and dialog body', () => {
    expect(PRICE_CARDS.trip).toBe(TripWatchCard)
    expect(cardFor('trip')).toBe(TripWatchCard)
    expect(DIALOG_BODIES.trip).toBe(TripDialogBody)
    expect(dialogBodyFor('trip')).toBe(TripDialogBody)
  })
})

describe('TripDialogBody', () => {
  it('before watching: the plan’s parts as the watch counts them, no guessed total', async () => {
    const parts = [
      { key: 'flights', label: 'Flights', amount: 612, note: 'tracked as the cheapest fare on your dates' },
      { key: 'activities', label: 'Activities', amount: 100, note: 'per person × 2' },
    ]
    await render(<TripDialogBody kind="trip" spec={{ plan_id: 3 }} preview={{ price: 712, parts }} />)
    expect(container.textContent).toContain('Flights')
    expect(container.textContent).toContain('$612')
    expect(container.textContent).toContain('tracked as the cheapest fare on your dates')
    expect(container.textContent).toContain('per person × 2')
    expect(container.textContent).not.toContain('$712') // the live total comes from the watch
    expect(container.textContent).toContain('Estimates are fixed and never trigger alerts')
  })

  it('once watched: each part says what its price is, and how it differs from My Plan', async () => {
    const rows = [
      { ...strip(FLIGHT), label: 'Flights — cheapest fare on your dates', detail: 'Google Flights · Berlin ⇄ Lisbon · 10–14 Dec · 2 travellers' },
      { ...SIM, detail: 'From your search (estimate)' },
    ]
    const watch = { ...TRIP, baseline_price: 555, last_price: 555, subject: { travellers: 2, components: rows }, last_observation: { breakdown: rows } }
    await render(<TripDialogBody kind="trip" spec={{ plan_id: 3 }} watch={watch} preview={{ planTotal: 625 }} />)
    expect(container.textContent).toContain('Google Flights · Berlin ⇄ Lisbon')
    const diff = container.querySelector('[data-testid="trip-total-diff"]')
    expect(diff.textContent).toContain('$70 less than your My Plan total ($625)')
    expect(diff.textContent).toContain('cheapest live fare on your dates')
  })

  it('once watched: a breakdown table with Live / Estimate badges and the total', async () => {
    await render(<TripDialogBody kind="trip" spec={{ plan_id: 3 }} watch={{ ...TRIP, last_price: 1023 }} />)
    const table = container.querySelector('table')
    expect(table.querySelector('caption').textContent).toMatch(/what we’re watching/i)
    const rows = [...table.querySelectorAll('tbody tr')].map(r => r.textContent)
    expect(rows[0]).toContain('Flights')
    expect(rows[0]).toContain('Live')
    expect(rows[3]).toContain('SIM / eSIM')
    expect(rows[3]).toContain('Estimate')
    expect(rows[2]).toContain('€24') // own currency …
    expect(rows[2]).toMatch(/not in total/i) // … and outside the USD total
    expect(table.querySelector('tfoot').textContent).toContain('$1,023')
    expect(container.textContent).toContain('Estimates are fixed and never trigger alerts')
  })
})

describe('TripWatchCard', () => {
  it('shows the stacked breakdown bar with an accessible summary', async () => {
    await render(<TripWatchCard watch={TRIP} onCheck={vi.fn()} onUpdate={vi.fn()} onDelete={vi.fn()} />)
    const bar = container.querySelector('[data-testid="trip-bar"]')
    expect(bar.getAttribute('role')).toBe('img')
    expect(bar.getAttribute('aria-label')).toBe('Flights 57%, Stay 37%, Activities 5%, Other 1%')
    expect(bar.querySelectorAll('[data-group]').length).toBe(4)
  })

  it('lists each part with its badge and the latest change', async () => {
    await render(<TripWatchCard watch={TRIP} onCheck={vi.fn()} onUpdate={vi.fn()} onDelete={vi.fn()} />)
    const list = container.querySelector('[aria-label="Trip price breakdown"]')
    expect(list.textContent).toContain('Lumen Hotel')
    expect(list.textContent).toContain('Live')
    expect(list.textContent).toContain('Estimate')
    expect(container.textContent).toContain('Last check: flights −$70, hotel −$42.')
    expect(list.textContent).toContain('from $22.87 per person × 2')
    expect(container.querySelector('svg[role="img"]')).not.toBeNull() // sparkline of the total
  })

  it('Re-plan starts a fresh search for the trip', async () => {
    await render(<TripWatchCard watch={TRIP} onCheck={vi.fn()} onUpdate={vi.fn()} onDelete={vi.fn()} />, '/alerts')
    await act(async () => button('Re-plan').click())
    expect(pending).toHaveBeenCalledWith(expect.objectContaining({
      origin: 'Berlin', destination: 'Lisbon', departure_date: '2099-12-10', num_travelers: 2, nationality: 'German',
    }))
    expect(location.pathname).toBe('/')
  })

  it('copes with a watch that has no breakdown yet', async () => {
    const bare = { ...TRIP, subject: {}, last_observation: null }
    await render(<TripWatchCard watch={bare} onCheck={vi.fn()} onUpdate={vi.fn()} onDelete={vi.fn()} />)
    expect(container.querySelector('[data-testid="trip-bar"]')).toBeNull()
    expect(button('Re-plan')).toBeUndefined()
  })
})

describe('WatchTripButton', () => {
  it('is hidden when signed out or without live prices', async () => {
    auth.token = null
    await render(<WatchTripButton plan={PLAN} />)
    expect(container.textContent).toBe('')
    auth.token = 'tok'
    alerts.caps = { serpapi: false, fareWatch: false, email: false }
    await render(<WatchTripButton plan={PLAN} />)
    expect(container.textContent).toBe('')
  })

  it('asks to save an unsaved plan first, legibly', async () => {
    await render(<WatchTripButton plan={null} showHint />)
    expect(container.textContent).toBe('Save your plan to watch its price')
    expect(container.querySelector('button')).toBeNull()
    expect(container.querySelector('p').className).not.toContain('text-gray-400')
  })

  it('in the drawer, says the watch uses the saved plan', async () => {
    await render(<WatchTripButton plan={PLAN} savedNote />)
    expect(container.textContent).toContain('Watches your saved plan — save any changes first.')
  })

  it('shows a keyboard focus ring on the dark header', async () => {
    await render(<WatchTripButton plan={PLAN} variant="onDark" />)
    expect(button('Watch whole trip').className).toContain('focus-visible:outline')
  })

  it('opens the dialog for the saved plan and creates the watch', async () => {
    api.createPriceWatch.mockResolvedValueOnce({ ...TRIP, already_watching: false })
    await render(<WatchTripButton plan={PLAN} />)
    expect(alerts.lastMatch).toEqual({ kind: 'trip', spec: { plan_id: 3 } })
    await act(async () => button('Watch whole trip').click())
    const dialog = document.querySelector('[role="dialog"]')
    expect(dialog.textContent).toContain('Watch this trip')
    await act(async () => button('Start watching', dialog).click())
    expect(api.createPriceWatch).toHaveBeenCalledWith(
      expect.objectContaining({ kind: 'trip', trip: { plan_id: 3 }, alert_mode: 'any_drop' }), 'tok')
    expect(setMatched).toHaveBeenCalledWith(expect.objectContaining({ id: 9 }))
    expect(document.querySelector('[role="dialog"] table')).not.toBeNull()
  })

  it('never seeds the target from the plan’s estimates (M8)', async () => {
    await render(<WatchTripButton plan={PLAN} />)
    await act(async () => button('Watch whole trip').click())
    await act(async () => document.querySelector('input[value="below_target"]').click())
    expect(document.querySelector('input[aria-label^="Target price in"]').value).toBe('')
  })

  it('reads "Watching · $X" once watched and opens the Alerts page', async () => {
    matched = { ...TRIP, last_price: 2140 }
    await render(<WatchTripButton plan={PLAN} />)
    const b = button('Watching')
    expect(b.textContent).toBe('Watching · $2,140')
    expect(b.getAttribute('aria-label')).toBe('Watching · $2,140 — open your alerts')
    await act(async () => b.click())
    expect(location.pathname + location.search).toBe('/alerts?kind=trip&watch=9')
  })

  it('is keyboard reachable as a real button', async () => {
    await render(<WatchTripButton plan={PLAN} />)
    const b = button('Watch whole trip')
    expect(b.tagName).toBe('BUTTON')
    expect(b.getAttribute('type')).toBe('button')
  })

  it('hides for a trip that has departed', async () => {
    await render(<WatchTripButton plan={{ ...PLAN, search_data: { ...PLAN.search_data, departure_date: '2000-01-01' } }} />)
    expect(container.textContent).toBe('')
  })
})

describe('alert kinds', () => {
  it('trip end / error notifications say trip; fare copy is unchanged', () => {
    const note = (kind, watch_kind) => ({ kind, data: watch_kind ? { watch_kind } : {} })
    expect(alertKindFor(note('watch_expired', 'trip')).action).toBe('See trip')
    expect(alertKindFor(note('watch_error', 'trip')).action).toBe('Check trip')
    expect(alertKindFor(note('watch_expired')).action).toBe('View')
    expect(alertKindFor(note('watch_error')).action).toBe('Retry')
    expect(alertKindFor(note('fare_drop')).action).toBe('See fare')
    expect(alertKindFor(note('trip_drop', 'trip')).action).toBe('See trip')
    expect(kindOf('watch_expired').action).toBe('View')
  })
})
