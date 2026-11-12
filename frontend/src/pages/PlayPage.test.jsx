// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'

const journey = vi.hoisted(() => ({ enabled: true }))
const cfg = vi.hoisted(() => ({ features: {} }))
vi.mock('../hooks/useClientConfig', () => ({ useClientConfig: () => ({ config: cfg, loaded: true }), featureOn: (c, k) => !!c.features?.[k] }))
vi.mock('../components/play/QuizHub', () => ({ default: () => <div data-tid="play.hub" /> }))
vi.mock('../components/play/H2HMatch', () => ({ default: () => <div data-tid="play.h2h.match" /> }))
vi.mock('../hooks/useJourney', () => ({ useJourney: () => ({ enabled: journey.enabled }) }))
vi.mock('../context/AuthContext', () => ({ useAuth: () => ({ token: 'tok' }) }))
vi.mock('../services/accountApi', () => ({ getAccount: vi.fn(), patchSettings: vi.fn() }))
vi.mock('../services/tripsApi', () => ({ getTripStats: vi.fn() }))
const acct = vi.hoisted(() => ({ settings: { hide_game: false } }))
vi.mock('../components/account/SettingsSync', () => ({ useAccountSettings: () => acct }))
vi.mock('../components/game/GameSection', () => ({ default: () => <div data-tid="game.section" /> }))
vi.mock('../components/game/useGameMe', () => ({
  default: () => ({ me: { hidden: false, streaks: { trip_checkin: { current: 3, longest: 5 } } } }),
}))

import { initI18n } from '../i18n/index'
import { getAccount, patchSettings } from '../services/accountApi'
import { getTripStats } from '../services/tripsApi'
import PlayPage from './PlayPage'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
const STATS = {
  countries: [{ code: 'PT', name: 'Portugal' }, { code: 'JP', name: 'Japan' }],
  continents: ['EU', 'AS'], bucket_goal: 30, trips_by_phase: {},
}
let container, root
const tid = (id) => container.querySelector(`[data-tid="${id}"]`)
const mount = async () => {
  await act(async () => { root.render(<MemoryRouter><PlayPage /></MemoryRouter>) })
}

beforeEach(async () => {
  await initI18n({ lng: 'en' })
  journey.enabled = true
  acct.settings = { hide_game: false }
  vi.clearAllMocks()
  getAccount.mockResolvedValue({ id: 1 })
  getTripStats.mockResolvedValue(STATS)
  patchSettings.mockResolvedValue({})
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container)
})
afterEach(() => { act(() => root.unmount()); container.remove() })

describe('PlayPage play flag', () => {
  it('hides the quiz hub when features.play is off or missing', async () => {
    cfg.features = {}
    await mount()
    expect(tid('play.hub')).toBeNull()
  })
  it('shows the hub when features.play is on, and nothing of it for a hidden game', async () => {
    cfg.features = { play: 1 }
    await mount()
    expect(tid('play.hub')).not.toBeNull()
    acct.settings = { hide_game: true }
    await mount()
    expect(tid('play.hub')).toBeNull()
    expect(tid('play.hidden')).not.toBeNull()
  })
  it('renders a match page on /play/h2h/:id only with the flag', async () => {
    cfg.features = { play: 1 }
    await act(async () => { root.render(<MemoryRouter><PlayPage h2hId="m1" /></MemoryRouter>) })
    expect(tid('play.h2h.match')).not.toBeNull()
  })
})

describe('PlayPage', () => {
  it('renders countries with names, flags, continents and the streak', async () => {
    await mount()
    expect(tid('game.section')).not.toBeNull()
    expect(tid('play.country.PT').textContent).toContain('Portugal')
    expect(tid('play.country.PT').textContent).toContain('\u{1F1F5}\u{1F1F9}')
    expect(tid('play.country.JP').textContent).toContain('Japan')
    expect(tid('play.continent.EU').textContent).toBe('Europe')
    expect(tid('play.streak.current').textContent).toBe('3 days in a row')
  })

  it('saves the bucket goal', async () => {
    await mount()
    const input = tid('play.goal.input')
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, '40')
      input.dispatchEvent(new Event('input', { bubbles: true }))
    })
    await act(async () => { tid('play.goal.save').click() })
    expect(patchSettings).toHaveBeenCalledWith('tok', { bucket_list_goal: 40 })
    expect(tid('play.goal.saved')).not.toBeNull()
  })

  it('rejects a goal outside 1..250', async () => {
    await mount()
    const input = tid('play.goal.input')
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, '251')
      input.dispatchEvent(new Event('input', { bubbles: true }))
    })
    expect(tid('play.goal.save').disabled).toBe(true)
    expect(tid('play.goal.invalid')).not.toBeNull()
  })

  it('with hide_game shows only the note linking to settings', async () => {
    acct.settings = { hide_game: true }
    await mount()
    expect(tid('play.hidden').textContent).toContain('hidden')
    expect(tid('play.hidden.settings').getAttribute('href')).toBe('/you')
    expect(tid('game.section')).toBeNull()
    expect(tid('play.countries')).toBeNull()
    expect(getTripStats).not.toHaveBeenCalled()
  })

  it('renders nothing when the journey is off', async () => {
    journey.enabled = false
    await mount()
    expect(container.innerHTML).toBe('')
  })
})
