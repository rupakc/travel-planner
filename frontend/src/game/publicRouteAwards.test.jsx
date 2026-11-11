// @vitest-environment jsdom
// Awards earned on a public route (/verify, /auth/callback, /auth/username)
// are announced before the signed-in layout — and its GameCelebration —
// mounts. They must still show as toasts there and send their telemetry.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter, Routes, Route } from 'react-router-dom'

const applySession = vi.fn(async () => {})
vi.mock('../context/AuthContext', () => ({ useAuth: () => ({ applySession, token: null }) }))
vi.mock('../services/authApi', () => ({
  verifyEmail: vi.fn(), resendVerification: vi.fn(), exchangeOAuthCode: vi.fn(), completeOAuthSignup: vi.fn(),
}))
vi.mock('../services/gameApi', () => ({
  getGameCatalog: vi.fn(async () => ({ badges: [{ id: 'verified', tier: 'bronze', icon: 'mail-check' }] })),
}))
vi.mock('../telemetry/client', () => ({ emit: vi.fn() }))
const account = { settings: { hide_game: false } }
let loadingSettings = false
vi.mock('../components/account/SettingsSync', () => ({
  useAccountSettings: () => account,
  useSettingsLoading: () => loadingSettings,
  settingsLoading: () => loadingSettings,
}))

import '../i18n'
import VerifyEmailPage from '../pages/VerifyEmailPage'
import OAuthCallbackPage from '../pages/OAuthCallbackPage'
import ChooseUsernamePage from '../pages/ChooseUsernamePage'
import GameCelebration from '../components/game/GameCelebration'
import { verifyEmail, exchangeOAuthCode, completeOAuthSignup } from '../services/authApi'
import { emit } from '../telemetry/client'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const GAME = {
  xp: 50,
  awards: [{ rule: 'email_verified', points: 50 }],
  badges: [{ id: 'verified', earned_at: '2026-11-11T10:00:00Z' }],
  level_up: null,
}
const SESSION = { access_token: 't', user: { username: 'jane' } }

let container, root
const tid = (id) => container.querySelectorAll(`[data-tid="${id}"]`)
// "*" stands in for the signed-in Layout, which mounts GameCelebration.
const mount = async (entry, path, page) => act(async () => root.render(
  <MemoryRouter initialEntries={[entry]}>
    <Routes>
      <Route path={path} element={page} />
      <Route path="*" element={<GameCelebration />} />
    </Routes>
  </MemoryRouter>))
const settle = () => act(async () => { await new Promise((r) => setTimeout(r, 0)) })

function expectCelebrated() {
  expect(tid('game.toast.award')).toHaveLength(1)
  expect(tid('game.toast.award')[0].textContent).toMatch(/50/)
  expect(tid('game.toast.badge')).toHaveLength(1)
  expect(emit).toHaveBeenCalledWith('game_award', { rule: 'email_verified', points: 50 })
  expect(emit).toHaveBeenCalledWith('badge_earned', { badge: 'verified' })
}

beforeEach(() => {
  vi.clearAllMocks()
  account.settings = { hide_game: false }
  loadingSettings = false
  window.matchMedia = vi.fn(() => ({ matches: true, addEventListener() {}, removeEventListener() {} }))
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})
afterEach(() => { act(() => root.unmount()); container.remove() })

describe('awards from public routes', () => {
  it('/verify: the +50 XP and Verified toasts show after landing signed in, with telemetry', async () => {
    window.history.replaceState(null, '', '/verify?token=abc')
    verifyEmail.mockResolvedValue({ status: 'verified', session: SESSION, game: GAME })
    await mount('/verify?token=abc', '/verify', <VerifyEmailPage />)
    await settle()
    expectCelebrated()
  })

  it('/auth/callback: a sign-in award shows on the return page', async () => {
    exchangeOAuthCode.mockResolvedValue({ status: 'signed_in', session: SESSION, game: GAME, return_to: '/' })
    await mount('/auth/callback?code=abc', '/auth/callback', <OAuthCallbackPage />)
    await settle()
    expectCelebrated()
  })

  it('/auth/username: a sign-up award shows on the return page', async () => {
    completeOAuthSignup.mockResolvedValue({ status: 'signed_in', session: SESSION, game: GAME })
    const oauth = { status: 'needs_username', signup_token: 'T', suggested_username: 'jane', display_name: 'Jane', email: null, invite_required: false, return_to: '/' }
    await mount({ pathname: '/auth/username', state: { oauth } }, '/auth/username', <ChooseUsernamePage />)
    await act(async () => {
      container.querySelector('[data-tid="oauth.username.form"]').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
    })
    await settle()
    expectCelebrated()
  })

  it('waits for the settings, and shows nothing when they hide the game', async () => {
    loadingSettings = true
    exchangeOAuthCode.mockResolvedValue({ status: 'signed_in', session: SESSION, game: GAME, return_to: '/' })
    await mount('/auth/callback?code=abc', '/auth/callback', <OAuthCallbackPage />)
    await settle()
    expect(tid('game.toast.award')).toHaveLength(0)
    loadingSettings = false
    account.settings = { hide_game: true }
    await mount('/', '/auth/callback', <OAuthCallbackPage />) // re-render: settings arrived
    await settle()
    expect(tid('game.toast.award')).toHaveLength(0)
    expect(emit).not.toHaveBeenCalledWith('game_award', expect.anything())
  })
})
