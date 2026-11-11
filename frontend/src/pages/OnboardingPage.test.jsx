// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom'

const journey = vi.hoisted(() => ({ value: { enabled: true, loaded: true } }))
const auth = vi.hoisted(() => ({ value: null }))
vi.mock('../hooks/useJourney', () => ({ useJourney: () => journey.value }))
vi.mock('../context/AuthContext', () => ({ useAuth: () => auth.value, useOptionalAuth: () => auth.value }))
vi.mock('../services/accountApi', () => ({ getAccount: vi.fn(), putOnboarding: vi.fn() }))
vi.mock('../game/announce', () => ({ announceGame: vi.fn() }))
vi.mock('../telemetry/client', () => ({ emit: vi.fn() }))

import { getAccount, putOnboarding } from '../services/accountApi'
import { announceGame } from '../game/announce'
import { emit } from '../telemetry/client'
import OnboardingPage from './OnboardingPage'
import OnboardingGate from '../components/onboarding/OnboardingGate'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

let container, root, loc, fetchMock
const realNotification = Object.getOwnPropertyDescriptor(window, 'Notification')

function Where() { loc = useLocation(); return null }
const tid = (id) => container.querySelector(`[data-tid="${id}"]`)
const click = async (id) => {
  const el = tid(id)
  if (!el) throw new Error(`no [data-tid="${id}"]`)
  await act(async () => { el.click() })
}
const flush = () => act(async () => { await new Promise((r) => setTimeout(r, 0)) })
const account = (onboarding) => ({ user: { id: 'u1' }, onboarding: { step: 0, done: false, skipped: false, traveller_type: null, ...onboarding } })
const prefs = { budget_category: 'medium', nationality: 'Indian', current_residence: '', residence_permits: [], existing_visas: [], interests: ['art'], num_travelers: 1, adults: 1, children: 0, seniors: 0, infants: 0, accessibility_needs: [] }

function setNotification(value) {
  if (value === undefined) delete window.Notification
  else Object.defineProperty(window, 'Notification', { value, configurable: true, writable: true })
}

async function renderPage(path = '/onboarding') {
  await act(async () => root.render(
    <MemoryRouter initialEntries={[path]}>
      <Where />
      <Routes>
        <Route path="/onboarding" element={<OnboardingPage />} />
        <Route path="*" element={<OnboardingGate />} />
      </Routes>
    </MemoryRouter>,
  ))
  await flush()
}

beforeEach(() => {
  journey.value = { enabled: true, loaded: true }
  auth.value = { token: 'tok', user: { id: 'u1' }, preferences: prefs, refreshPreferences: vi.fn() }
  getAccount.mockReset()
  putOnboarding.mockReset().mockResolvedValue({ onboarding: {}, game: null })
  announceGame.mockReset()
  emit.mockReset()
  localStorage.clear()
  sessionStorage.clear()
  fetchMock = vi.fn(async (url, init = {}) => {
    if (url === '/api/preferences' && (!init.method || init.method === 'GET')) {
      return { ok: true, status: 200, json: async () => ({ ...prefs, username: 'jane' }) }
    }
    if (url === '/api/preferences' && init.method === 'PUT') {
      return { ok: true, status: 200, json: async () => JSON.parse(init.body) }
    }
    return { ok: false, status: 404, json: async () => ({}) }
  })
  vi.stubGlobal('fetch', fetchMock)
  setNotification({ permission: 'default', requestPermission: vi.fn().mockResolvedValue('granted') })
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container)
})
afterEach(() => {
  act(() => root.unmount()); container.remove()
  vi.unstubAllGlobals()
  if (realNotification) Object.defineProperty(window, 'Notification', realNotification)
  else delete window.Notification
})

describe('OnboardingPage', () => {
  it('renders nothing when the journey is off', async () => {
    journey.value = { enabled: false, loaded: true }
    getAccount.mockResolvedValue(account({}))
    await renderPage()
    expect(container.innerHTML).toBe('')
    expect(putOnboarding).not.toHaveBeenCalled()
  })

  it('starts at the welcome step and reports it', async () => {
    getAccount.mockResolvedValue(account({ step: 0 }))
    await renderPage()
    expect(tid('onboarding.step.welcome')).not.toBeNull()
    expect(tid('onboarding.resume')).toBeNull()
    expect(putOnboarding).toHaveBeenCalledWith('tok', { step: 1, done: false })
    expect(emit).toHaveBeenCalledWith('onboarding_step', { step: 1, action: 'view' })
  })

  it('resumes at step 3 from onboarding.step', async () => {
    getAccount.mockResolvedValue(account({ step: 3 }))
    await renderPage()
    expect(tid('onboarding.step.home')).not.toBeNull()
    expect(tid('onboarding.resume')).not.toBeNull()
    expect(container.textContent).toContain('Step 3 of 5')
    expect(putOnboarding).toHaveBeenCalledWith('tok', { step: 3, done: false })
    expect(putOnboarding).not.toHaveBeenCalledWith('tok', { step: 1, done: false })
  })

  it('starts at the welcome step when /account fails', async () => {
    getAccount.mockRejectedValue({ status: 500 })
    await renderPage()
    expect(tid('onboarding.step.welcome')).not.toBeNull()
  })

  it('Skip sends skipped: true and leaves', async () => {
    getAccount.mockResolvedValue(account({ step: 2 }))
    await renderPage()
    await click('onboarding.skip-all')
    await flush()
    expect(putOnboarding).toHaveBeenLastCalledWith('tok', { step: 2, done: true, skipped: true })
    expect(emit).toHaveBeenCalledWith('onboarding_step', { step: 2, action: 'skip' })
    expect(sessionStorage.getItem('tp_onboarding_seen')).toBe('1')
    expect(loc.pathname).toBe('/')
  })

  it('runs the quiz, shows the type and keeps the answers on the device', async () => {
    getAccount.mockResolvedValue(account({ step: 1 }))
    await renderPage()
    await click('onboarding.next')
    expect(tid('onboarding.step.quiz')).not.toBeNull()
    expect(tid('onboarding.quiz.next').disabled).toBe(true)
    await click('onboarding.option.companions.work')
    expect(tid('onboarding.option.companions.work').getAttribute('aria-checked')).toBe('true')
    await click('onboarding.quiz.next')
    // budget, interests, pace, planning skipped; needs answered.
    for (let i = 0; i < 4; i++) await click('onboarding.quiz.skip')
    await click('onboarding.option.needs.wheelchair')
    await click('onboarding.quiz.next')
    expect(tid('onboarding.result')).not.toBeNull()
    expect(tid('onboarding.result.primary').textContent).toBe('Business Traveller')
    expect(container.textContent).toContain('Accessible Traveller')
    expect(emit).toHaveBeenCalledWith('onboarding_result', { type: 'business', secondary: 1 })
    expect(JSON.parse(localStorage.getItem('tp_quiz_u1'))).toMatchObject({ companions: ['work'], needs: ['wheelchair'] })

    await click('onboarding.change-answers')
    expect(tid('onboarding.option.companions.work').getAttribute('aria-checked')).toBe('true')
  })

  it('requests the notification permission only after Allow', async () => {
    getAccount.mockResolvedValue(account({ step: 4 }))
    await renderPage()
    expect(tid('onboarding.step.notifications')).not.toBeNull()
    expect(window.Notification.requestPermission).not.toHaveBeenCalled()
    await click('onboarding.notifications.allow')
    await flush()
    expect(window.Notification.requestPermission).toHaveBeenCalledTimes(1)
    expect(tid('onboarding.step.first-trip')).not.toBeNull()
  })

  it('Not now moves on without asking the browser', async () => {
    getAccount.mockResolvedValue(account({ step: 4 }))
    await renderPage()
    await click('onboarding.notifications.later')
    expect(window.Notification.requestPermission).not.toHaveBeenCalled()
    expect(tid('onboarding.step.first-trip')).not.toBeNull()
  })

  it('says when the browser blocks notifications', async () => {
    setNotification({ permission: 'denied', requestPermission: vi.fn() })
    getAccount.mockResolvedValue(account({ step: 4 }))
    await renderPage()
    expect(tid('onboarding.notifications.blocked').textContent).toContain('Your browser blocks notifications')
    expect(tid('onboarding.notifications.allow')).toBeNull()
  })

  it('skips the notifications step when the browser has no Notification API', async () => {
    setNotification(undefined)
    getAccount.mockResolvedValue(account({ step: 3 }))
    await renderPage()
    await click('onboarding.next')
    expect(tid('onboarding.step.first-trip')).not.toBeNull()
    expect(putOnboarding).not.toHaveBeenCalledWith('tok', { step: 4, done: false })
    await click('onboarding.back')
    expect(tid('onboarding.step.home')).not.toBeNull()
  })

  it('finishes: merges preferences, marks onboarding done and opens Explore', async () => {
    localStorage.setItem('tp_quiz_u1', JSON.stringify({ companions: ['partner'], interests: ['food'] }))
    const game = { awards: [{ rule: 'traveller_type', points: 25 }], badges: [], level_up: null }
    putOnboarding.mockImplementation(async (_t, body) => ({ onboarding: body, game: body.done ? game : null }))
    getAccount.mockResolvedValue(account({ step: 5 }))
    await renderPage()
    await click('onboarding.first-trip')
    await flush()
    const put = fetchMock.mock.calls.find(([, init]) => init?.method === 'PUT')
    const body = JSON.parse(put[1].body)
    expect(body).toMatchObject({ nationality: 'Indian', adults: 2, num_travelers: 2, interests: ['art', 'food'] })
    expect(put[1].headers.Authorization).toBe('Bearer tok')
    expect(putOnboarding).toHaveBeenLastCalledWith('tok', { step: 5, done: true, traveller_type: 'culture_foodie' })
    expect(announceGame).toHaveBeenCalledWith(game)
    expect(auth.value.refreshPreferences).toHaveBeenCalled()
    expect(emit).toHaveBeenCalledWith('onboarding_step', { step: 5, action: 'done' })
    expect(loc.pathname).toBe('/explore')
  })

  it('on a preferences failure offers Retry and Continue without syncing', async () => {
    getAccount.mockResolvedValue(account({ step: 5 }))
    let fail = true
    fetchMock.mockImplementation(async (url, init = {}) => {
      if (init.method === 'PUT') {
        return fail
          ? { ok: false, status: 500, json: async () => ({ detail: 'Database is busy' }) }
          : { ok: true, status: 200, json: async () => ({}) }
      }
      return { ok: true, status: 200, json: async () => prefs }
    })
    await renderPage()
    await click('onboarding.explore')
    await flush()
    expect(tid('onboarding.sync-error').textContent).toContain('Database is busy')
    expect(putOnboarding).not.toHaveBeenCalledWith('tok', expect.objectContaining({ done: true }))
    expect(loc.pathname).toBe('/onboarding')

    await click('onboarding.retry')
    await flush()
    expect(tid('onboarding.sync-error')).not.toBeNull()

    await click('onboarding.continue-unsynced')
    await flush()
    expect(putOnboarding).toHaveBeenLastCalledWith('tok', { step: 5, done: true, traveller_type: 'culture_foodie' })
    expect(loc.pathname).toBe('/')
    fail = false
  })

  it('saves the passport as nationality and the home airport on the device', async () => {
    getAccount.mockResolvedValue(account({ step: 3 }))
    await renderPage()
    const input = tid('onboarding.home-airport').querySelector('input')
    await act(async () => {
      const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set
      set.call(input, 'LIS')
      input.dispatchEvent(new Event('input', { bubbles: true }))
    })
    await click('onboarding.next')
    expect(localStorage.getItem('tp_home_airport_u1')).toBe('LIS')
  })
})

describe('OnboardingGate', () => {
  it('sends a user who has not finished to /onboarding, once', async () => {
    getAccount.mockResolvedValue(account({ done: false }))
    await renderPage('/trips')
    expect(loc.pathname).toBe('/onboarding')
    expect(sessionStorage.getItem('tp_onboarding_seen')).toBe('1')

    act(() => root.unmount()); root = createRoot(container)
    getAccount.mockClear()
    await renderPage('/trips')
    expect(loc.pathname).toBe('/trips')
    expect(getAccount).not.toHaveBeenCalled()
  })

  it('never redirects on a 404 or an error from /account', async () => {
    getAccount.mockRejectedValue({ status: 404 })
    await renderPage('/trips')
    expect(loc.pathname).toBe('/trips')
    act(() => root.unmount()); root = createRoot(container)
    getAccount.mockRejectedValue({ status: 500 })
    await renderPage('/trips')
    expect(loc.pathname).toBe('/trips')
    expect(sessionStorage.getItem('tp_onboarding_seen')).toBeNull()
  })

  it('stays put when onboarding is done or missing', async () => {
    getAccount.mockResolvedValue(account({ done: true }))
    await renderPage('/trips')
    expect(loc.pathname).toBe('/trips')
    act(() => root.unmount()); root = createRoot(container)
    getAccount.mockResolvedValue({ user: { id: 'u1' } })
    await renderPage('/trips')
    expect(loc.pathname).toBe('/trips')
  })

  it('does nothing when the journey is off or nobody is signed in', async () => {
    getAccount.mockResolvedValue(account({ done: false }))
    journey.value = { enabled: false, loaded: true }
    await renderPage('/trips')
    expect(loc.pathname).toBe('/trips')
    act(() => root.unmount()); root = createRoot(container)
    journey.value = { enabled: true, loaded: true }
    auth.value = { token: null, user: null }
    await renderPage('/trips')
    expect(loc.pathname).toBe('/trips')
    expect(getAccount).not.toHaveBeenCalled()
  })
})
