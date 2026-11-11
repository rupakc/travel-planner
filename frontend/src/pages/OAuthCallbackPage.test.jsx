// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom'

const exchangeOAuthCode = vi.fn()
vi.mock('../services/authApi', () => ({ exchangeOAuthCode: (...a) => exchangeOAuthCode(...a) }))
const applySession = vi.fn()
vi.mock('../context/AuthContext', () => ({ useAuth: () => ({ applySession }) }))
vi.mock('../telemetry/client', () => ({ emit: vi.fn() }))
const announceGame = vi.fn()
vi.mock('../game/announce', () => ({ announceGame: (...a) => announceGame(...a) }))
import '../i18n'
import OAuthCallbackPage from './OAuthCallbackPage'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
let container, root, seen

function Probe() { seen = useLocation(); return <div data-tid="probe" /> }
const mount = async (url) => act(async () => root.render(
  <MemoryRouter initialEntries={[url]}>
    <Routes>
      <Route path="/auth/callback" element={<OAuthCallbackPage />} />
      <Route path="*" element={<Probe />} />
    </Routes>
  </MemoryRouter>))

beforeEach(() => {
  container = document.createElement('div'); document.body.appendChild(container)
  root = createRoot(container)
  exchangeOAuthCode.mockReset(); applySession.mockReset(); announceGame.mockReset()
  vi.spyOn(window.history, 'replaceState')
})
afterEach(() => { act(() => root.unmount()); container.remove(); vi.restoreAllMocks() })

describe('OAuthCallbackPage', () => {
  it('maps email_in_use_unverified to the sign-in-then-connect note', async () => {
    await mount('/auth/callback?error=email_in_use_unverified')
    expect(seen.pathname).toBe('/login')
    expect(seen.state.notice).toMatch(/Sign in with your password, then connect/)
  })

  it('translates other callback codes through the errors namespace', async () => {
    await mount('/auth/callback?error=cancelled')
    expect(seen.pathname).toBe('/login')
    expect(seen.state.notice).toBe('Sign-in was cancelled.')
  })

  it('strips the code from the URL before exchanging', async () => {
    const order = []
    window.history.replaceState.mockImplementation(() => order.push('strip'))
    exchangeOAuthCode.mockImplementation(() => { order.push('exchange'); return new Promise(() => {}) })
    await mount('/auth/callback?code=abc')
    expect(order).toEqual(['strip', 'exchange'])
    expect(exchangeOAuthCode).toHaveBeenCalledWith('abc')
  })

  it('signs in and returns to a validated return_to', async () => {
    exchangeOAuthCode.mockResolvedValue({ status: 'signed_in', session: { access_token: 't' }, game: { awards: [] }, return_to: '/chat' })
    await mount('/auth/callback?code=abc')
    expect(applySession).toHaveBeenCalledWith({ access_token: 't' })
    expect(seen.pathname).toBe('/chat')
  })

  it('falls back to / for a foreign return_to', async () => {
    exchangeOAuthCode.mockResolvedValue({ status: 'signed_in', session: {}, return_to: '//evil.com' })
    await mount('/auth/callback?code=abc')
    expect(seen.pathname).toBe('/')
  })

  it('needs_username passes the result in router state, never in the URL', async () => {
    exchangeOAuthCode.mockResolvedValue({ status: 'needs_username', signup_token: 'SECRET', suggested_username: 'jane', return_to: '/' })
    await mount('/auth/callback?code=abc')
    expect(seen.pathname).toBe('/auth/username')
    expect(seen.search).toBe('')
    expect(seen.state.oauth.signup_token).toBe('SECRET')
  })

  it('linked goes to /account with a toast', async () => {
    exchangeOAuthCode.mockResolvedValue({ status: 'linked', provider: 'github', return_to: '/account' })
    await mount('/auth/callback?code=abc')
    expect(seen.pathname).toBe('/account')
    expect(seen.state.toast).toBe('Account connected.')
  })

  it('a rejected exchange returns to /login with the code text', async () => {
    exchangeOAuthCode.mockRejectedValue({ status: 400, code: 'code_invalid', detail: 'bad' })
    await mount('/auth/callback?code=abc')
    expect(seen.pathname).toBe('/login')
    expect(seen.state.notice).toBeTruthy()
  })
})
