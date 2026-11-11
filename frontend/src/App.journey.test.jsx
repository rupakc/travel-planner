// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter, useLocation } from 'react-router-dom'

const auth = vi.hoisted(() => ({ value: {} }))
const journey = vi.hoisted(() => ({ value: {} }))
const trips = vi.hoisted(() => ({ value: {} }))
vi.mock('./context/AuthContext', () => ({ useAuth: () => auth.value }))
vi.mock('./hooks/useJourney', () => ({ useJourney: () => journey.value }))
vi.mock('./hooks/useHasTrips', () => ({ useHasTrips: () => trips.value }))
vi.mock('./context/AlertsContext', () => ({ AlertsProvider: ({ children }) => children }))
vi.mock('./utils/analytics', () => ({ track: vi.fn() }))
vi.mock('./telemetry/client', () => ({ screenView: vi.fn(), setUserPresent: vi.fn() }))

const { marker, blank } = vi.hoisted(() => ({
  marker: (name) => ({ default: (props) => <div data-page={name} data-props={JSON.stringify(props)} /> }),
  blank: { default: () => null },
}))
vi.mock('./pages/SearchPage', () => marker('search'))
vi.mock('./pages/ResultsPage', () => marker('results'))
vi.mock('./pages/ChatPage', () => marker('chat'))
vi.mock('./pages/PreferencesPage', () => marker('preferences'))
vi.mock('./pages/AlertsPage', () => marker('alerts'))
vi.mock('./pages/NearbyPage', () => marker('nearby'))
vi.mock('./pages/AccountPage', () => marker('account'))
vi.mock('./pages/AdminPage', () => marker('admin'))
vi.mock('./pages/LoginPage', () => marker('login'))
vi.mock('./pages/TripsPage', () => marker('trips'))
vi.mock('./pages/TripPage', () => marker('trip'))
vi.mock('./pages/PlayPage', () => marker('play'))
vi.mock('./pages/YouPage', () => marker('you'))
vi.mock('./pages/OnboardingPage', () => marker('onboarding'))
vi.mock('./components/ui/NavBar', () => blank)
vi.mock('./components/FeedbackWidget', () => blank)
vi.mock('./components/ui/AttributionFooter', () => blank)
vi.mock('./components/ConsentPrompt', () => blank)
vi.mock('./components/alerts/AlertToast', () => blank)
vi.mock('./components/account/SettingsSync', () => blank)
vi.mock('./components/account/VerifyBanner', () => blank)
vi.mock('./components/game/GameCelebration', () => blank)

import App from './App'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
let container, root

function Where() { return <output data-where={useLocation().pathname} /> }

async function visit(path) {
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  await act(async () => root.render(
    <MemoryRouter initialEntries={[path]}><App /><Where /></MemoryRouter>))
}
const where = () => container.querySelector('[data-where]').getAttribute('data-where')
// The always-mounted tabs stay in the DOM; "shown" means not inside display:none.
const shown = (name) => {
  const el = container.querySelector(`[data-page="${name}"]`)
  if (!el) return false
  for (let n = el; n && n !== container; n = n.parentElement) if (n.style?.display === 'none') return false
  return true
}
const props = (name) => JSON.parse(container.querySelector(`[data-page="${name}"]`).getAttribute('data-props'))

const signedIn = { isAuthenticated: true, loading: false, token: 'tok', user: { id: 1, username: 'a' }, isAdmin: false }
const OFF = { enabled: false, tripsApi: false, offlinePack: false, loaded: true }
const ON = { enabled: true, tripsApi: true, offlinePack: true, loaded: true }

beforeEach(() => {
  auth.value = signedIn
  journey.value = OFF
  trips.value = { hasTrips: false, loading: false }
})
afterEach(() => { act(() => root.unmount()); container.remove() })

describe('App with the journey off (classic shell)', () => {
  it('/ renders SearchPage', async () => {
    await visit('/')
    expect(shown('search')).toBe(true)
    expect(container.querySelector('[data-page="trips"]')).toBeNull()
  })

  it('/trips/3 redirects to /', async () => {
    await visit('/trips/3')
    expect(where()).toBe('/')
    expect(shown('search')).toBe(true)
  })

  it.each(['/trips', '/explore', '/play', '/you'])('%s redirects to /', async (path) => {
    await visit(path)
    expect(where()).toBe('/')
  })

  it('keeps the classic routes', async () => {
    await visit('/chat')
    expect(shown('chat')).toBe(true)
    expect(shown('search')).toBe(false)
  })
})

describe('App with the journey on', () => {
  beforeEach(() => { journey.value = ON })

  it('signed in with trips: / renders TripsPage', async () => {
    trips.value = { hasTrips: true, loading: false }
    await visit('/')
    expect(shown('trips')).toBe(true)
    expect(shown('search')).toBe(false)
  })

  it('zero trips: / renders SearchPage', async () => {
    await visit('/')
    expect(shown('search')).toBe(true)
    expect(container.querySelector('[data-page="trips"]')).toBeNull()
  })

  it('signed in while the trips check loads: a neutral skeleton at /', async () => {
    trips.value = { hasTrips: null, loading: true }
    await visit('/')
    expect(shown('search')).toBe(false)
    expect(container.querySelector('[data-page="trips"]')).toBeNull()
    expect(container.querySelector('[data-tid="journey.homeLoading"]')).not.toBeNull()
  })

  it('signed out: / goes to sign-in, never the trips hub', async () => {
    auth.value = { isAuthenticated: false, loading: false, token: null, user: null }
    trips.value = { hasTrips: false, loading: false }
    await visit('/')
    expect(container.querySelector('[data-page="trips"]')).toBeNull()
  })

  it('/trips renders TripsPage', async () => {
    await visit('/trips')
    expect(shown('trips')).toBe(true)
  })

  it('/explore shows the always-mounted search', async () => {
    trips.value = { hasTrips: true, loading: false }
    await visit('/explore')
    expect(shown('search')).toBe(true)
    expect(shown('trips')).toBe(false)
  })

  it('/trips/3/today renders TripPage with the id and tab', async () => {
    await visit('/trips/3/today')
    expect(shown('trip')).toBe(true)
    expect(props('trip')).toEqual({ tripId: 3, tab: 'today' })
  })

  it('/trips/3 renders TripPage without a tab', async () => {
    await visit('/trips/3')
    expect(props('trip')).toEqual({ tripId: 3, tab: null })
  })

  it.each(['/trips/abc', '/trips/3/bogus'])('%s redirects to /', async (path) => {
    await visit(path)
    expect(where()).toBe('/')
  })

  it('/play and /you render their pages', async () => {
    await visit('/play')
    expect(shown('play')).toBe(true)
    act(() => root.unmount()); container.remove()
    await visit('/you')
    expect(shown('you')).toBe(true)
  })

  it('/onboarding is a full-screen route', async () => {
    await visit('/onboarding')
    expect(shown('onboarding')).toBe(true)
    expect(container.querySelector('[data-page="search"]')).toBeNull()
  })

  it('a deep link waits for /config instead of redirecting', async () => {
    journey.value = { enabled: false, tripsApi: false, offlinePack: false, loaded: false }
    await visit('/trips/12/offline')
    expect(where()).toBe('/trips/12/offline')
  })
})
