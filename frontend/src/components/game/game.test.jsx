// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'

const auth = { token: 'tok' }
vi.mock('../../context/AuthContext', () => ({ useAuth: () => auth }))
vi.mock('../../services/gameApi', () => ({ getGameMe: vi.fn(), getGameCatalog: vi.fn() }))
vi.mock('../../telemetry/client', () => ({ emit: vi.fn() }))
const account = { settings: { hide_game: false } }
vi.mock('../account/SettingsSync', () => ({ useAccountSettings: () => account }))

import GameNavChip from './GameNavChip'
import GameSection from './GameSection'
import GameCelebration, { DISMISS_MS } from './GameCelebration'
import { getGameMe, getGameCatalog } from '../../services/gameApi'
import { announceGame } from '../../game/announce'
import { emit } from '../../telemetry/client'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const ME = {
  xp: 150, level: 2, level_min_xp: 100, next_level_xp: 250,
  badges: [{ id: 'verified', progress: 1, target: 1, earned_at: '2026-11-11T10:00:00Z' }],
  streaks: {}, recent: [{ rule: 'email_verified', points: 50, created_at: '2026-11-11T10:00:00Z' }], hidden: false,
}
const CATALOG = {
  version: 1,
  rules: [{ id: 'email_verified', points: 50, daily_cap: 1, once: true }],
  badges: [
    { id: 'verified', rule: 'email_verified', target: 1, tier: 'bronze', icon: 'mail-check' },
    { id: 'first_steps', rule: 'onboarding_complete', target: 1, tier: 'bronze', icon: 'footprints' },
  ],
  levels: [{ level: 1, min_xp: 0 }],
}
const notFound = () => Promise.reject(Object.assign(new Error('nf'), { status: 404 }))

let container, root
const render = async (el) => { await act(async () => root.render(<MemoryRouter>{el}</MemoryRouter>)) }
const tid = (id) => container.querySelector(`[data-tid="${id}"]`)
const setReduced = (on) => {
  window.matchMedia = vi.fn(() => ({ matches: on, addEventListener() {}, removeEventListener() {} }))
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.useRealTimers()
  auth.token = 'tok'
  account.settings = { hide_game: false }
  setReduced(false)
  getGameMe.mockResolvedValue(ME)
  getGameCatalog.mockResolvedValue(CATALOG)
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})
afterEach(() => { act(() => root.unmount()); container.remove() })

describe('GameNavChip', () => {
  it('shows the level with a progress ring', async () => {
    await render(<GameNavChip />)
    expect(tid('game.navChip').textContent).toContain('Lv 2')
    // 50 of 150 XP into the level
    const ring = tid('game.navChip.ring')
    const c = 2 * Math.PI * 9
    expect(Number(ring.getAttribute('stroke-dashoffset'))).toBeCloseTo(c * (1 - 50 / 150), 3)
    expect(emit).toHaveBeenCalledWith('game_view', { surface: 'nav' })
  })
  it('hides on a 404 without an error', async () => {
    getGameMe.mockImplementation(notFound)
    const err = vi.spyOn(console, 'error').mockImplementation(() => {})
    await render(<GameNavChip />)
    expect(tid('game.navChip')).toBeNull()
    expect(err).not.toHaveBeenCalled()
    err.mockRestore()
  })
  it('hides when signed out, and when hide_game is on (no request)', async () => {
    auth.token = null
    await render(<GameNavChip />)
    expect(tid('game.navChip')).toBeNull()
    auth.token = 'tok'
    account.settings = { hide_game: true }
    await render(<GameNavChip />)
    expect(tid('game.navChip')).toBeNull()
    expect(getGameMe).not.toHaveBeenCalled()
  })
  it('refreshes after an award is announced', async () => {
    await render(<GameNavChip />)
    getGameMe.mockResolvedValue({ ...ME, xp: 250, level: 3, level_min_xp: 250, next_level_xp: 500 })
    await act(async () => announceGame({ xp: 250, awards: [{ rule: 'email_verified', points: 50 }], badges: [], level_up: null }))
    expect(tid('game.navChip').textContent).toContain('Lv 3')
  })
})

describe('GameSection', () => {
  it('renders nothing without an account payload', async () => {
    await render(<GameSection account={null} />)
    expect(container.innerHTML).toBe('')
  })
  it('shows XP, level, progress, earned and greyed badges and recent awards', async () => {
    await render(<GameSection account={{}} />)
    expect(tid('game.xp').textContent).toBe('150 XP')
    expect(tid('game.level').textContent).toBe('Level 2')
    expect(tid('game.progress').getAttribute('aria-valuenow')).toBe('33')
    expect(tid('game.badge.verified').dataset.earned).toBe('true')
    expect(tid('game.badge.verified').textContent).toContain('Verified')
    const locked = tid('game.badge.first_steps')
    expect(locked.dataset.earned).toBe('false')
    expect(locked.textContent).toContain('0/1')
    expect(tid('game.recent').textContent).toContain('Email confirmed')
    expect(tid('game.recent').textContent).toContain('+50 XP')
  })
  it('hides on a 404 and when hide_game is on', async () => {
    getGameMe.mockImplementation(notFound)
    await render(<GameSection account={{}} />)
    expect(container.innerHTML).toBe('')
    getGameMe.mockResolvedValue(ME)
    account.settings = { hide_game: true }
    await render(<GameSection account={{}} />)
    expect(container.innerHTML).toBe('')
  })
})

describe('GameCelebration', () => {
  const badgeDelta = {
    xp: 150,
    awards: [{ rule: 'email_verified', points: 50 }],
    badges: [{ id: 'verified', earned_at: '2026-11-11T10:00:00Z' }],
    level_up: { from: 1, to: 2 },
  }

  it('toasts the award, the badge name from the catalogue and the new level', async () => {
    await render(<GameCelebration />)
    await act(async () => announceGame(badgeDelta))
    expect(tid('game.toast.award').textContent).toContain('+50 XP — Email confirmed')
    expect(tid('game.toast.badge').textContent).toContain('Verified')
    expect(tid('game.toast.level').textContent).toContain('Level 2!')
    expect(container.querySelector('.game-confetti')).not.toBeNull()
    expect(emit).toHaveBeenCalledWith('game_award', { rule: 'email_verified', points: 50 })
    expect(emit).toHaveBeenCalledWith('badge_earned', { badge: 'verified' })
    expect(emit).toHaveBeenCalledWith('level_up', { level: 2 })
  })
  it('is a polite live region that never takes pointer input', async () => {
    await render(<GameCelebration />)
    const live = tid('game.celebration')
    expect(live.getAttribute('aria-live')).toBe('polite')
    expect(live.className).toContain('pointer-events-none')
  })
  it('has no confetti under reduced motion', async () => {
    setReduced(true)
    await render(<GameCelebration />)
    await act(async () => announceGame(badgeDelta))
    expect(tid('game.toast.badge')).not.toBeNull()
    expect(container.querySelector('.game-confetti')).toBeNull()
  })
  it('dismisses itself after 4 seconds', async () => {
    vi.useFakeTimers()
    await render(<GameCelebration />)
    await act(async () => announceGame(badgeDelta))
    expect(tid('game.toast.award')).not.toBeNull()
    await act(async () => { vi.advanceTimersByTime(DISMISS_MS + 50) })
    expect(tid('game.toast.award')).toBeNull()
    expect(tid('game.toast.badge')).toBeNull()
  })
  it('still names the badge when the catalogue is unavailable', async () => {
    getGameCatalog.mockImplementation(notFound)
    await render(<GameCelebration />)
    await act(async () => announceGame(badgeDelta))
    expect(tid('game.toast.badge').textContent).toContain('Verified')
  })
  it('renders nothing and emits nothing when hide_game is on', async () => {
    account.settings = { hide_game: true }
    await render(<GameCelebration />)
    await act(async () => announceGame(badgeDelta))
    expect(container.innerHTML).toBe('')
    expect(emit).not.toHaveBeenCalled()
  })
})
