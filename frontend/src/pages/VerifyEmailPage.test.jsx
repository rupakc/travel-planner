// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { StrictMode } from 'react'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom'

const auth = { applySession: vi.fn(async () => {}) }
vi.mock('../context/AuthContext', () => ({ useAuth: () => auth }))
vi.mock('../services/authApi', () => ({ verifyEmail: vi.fn(), resendVerification: vi.fn() }))
vi.mock('../game/announce', () => ({ announceGame: vi.fn() }))
vi.mock('../telemetry/client', () => ({ emit: vi.fn() }))

import VerifyEmailPage from './VerifyEmailPage'
import { verifyEmail, resendVerification } from '../services/authApi'
import { announceGame } from '../game/announce'
import { emit } from '../telemetry/client'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

let container, root, where
function Where() { where = useLocation(); return null }
const render = async (strict = false) => {
  const tree = (
    <MemoryRouter initialEntries={['/verify?token=abc123']}>
      <Where />
      <Routes><Route path="/verify" element={<VerifyEmailPage />} /><Route path="*" element={<p>elsewhere</p>} /></Routes>
    </MemoryRouter>
  )
  await act(async () => root.render(strict ? <StrictMode>{tree}</StrictMode> : tree))
}
const tid = (id) => container.querySelector(`[data-tid="${id}"]`)

beforeEach(() => {
  vi.clearAllMocks()
  window.history.replaceState(null, '', '/verify?token=abc123')
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})
afterEach(() => { act(() => root.unmount()); container.remove() })

describe('VerifyEmailPage', () => {
  it('drops the token from the URL before verifyEmail resolves', async () => {
    let seenUrl
    let release
    verifyEmail.mockImplementation(() => new Promise((res) => { seenUrl = window.location.search; release = res }))
    await render()
    expect(verifyEmail).toHaveBeenCalledWith('abc123')
    expect(seenUrl).toBe('')
    expect(window.location.href).not.toContain('abc123')
    await act(async () => release({ status: 'verified', session: null, game: null }))
  })

  it('posts once under StrictMode', async () => {
    verifyEmail.mockResolvedValue({ status: 'verified', session: null, game: null })
    await render(true)
    expect(verifyEmail).toHaveBeenCalledTimes(1)
  })

  it('does not call the API without a token', async () => {
    window.history.replaceState(null, '', '/verify')
    await act(async () => root.render(<MemoryRouter initialEntries={['/verify']}><VerifyEmailPage /></MemoryRouter>))
    expect(verifyEmail).not.toHaveBeenCalled()
    expect(tid('verify-invalid')).toBeTruthy()
  })

  it('applies the session, announces the game delta and goes home', async () => {
    const session = { access_token: 't' }
    const game = { awards: [{ xp: 10 }] }
    verifyEmail.mockResolvedValue({ status: 'verified', session, game })
    await render()
    expect(auth.applySession).toHaveBeenCalledWith(session)
    expect(announceGame).toHaveBeenCalledWith(game)
    expect(where.pathname).toBe('/')
    expect(emit).toHaveBeenCalledWith('email_verify', { result: 'ok' })
  })

  it('falls back to Email confirmed with a sign-in link when applySession throws', async () => {
    verifyEmail.mockResolvedValue({ status: 'verified', session: { access_token: 't' }, game: null })
    auth.applySession.mockRejectedValueOnce(new Error('boom'))
    await render()
    expect(tid('verify-confirmed')).toBeTruthy()
    expect(tid('verify-login-link').getAttribute('href')).toBe('/login')
    expect(container.querySelector('[role="alert"]')).toBeNull()
    expect(emit.mock.calls.filter((c) => c[0] === 'email_verify')).toEqual([['email_verify', { result: 'ok' }]])
  })

  it('shows Email confirmed with an account link when there is no session', async () => {
    verifyEmail.mockResolvedValue({ status: 'verified', session: null, game: null })
    await render()
    expect(tid('verify-confirmed')).toBeTruthy()
    expect(tid('verify-account-link').getAttribute('href')).toBe('/account')
    expect(auth.applySession).not.toHaveBeenCalled()
  })

  it('renders already-confirmed on token_used', async () => {
    verifyEmail.mockRejectedValue({ status: 409, code: 'token_used' })
    await render()
    expect(tid('verify-used').textContent).toMatch(/already confirmed/i)
    expect(tid('verify-login-link').getAttribute('href')).toBe('/login')
    expect(container.querySelector('[role="alert"]')).toBeNull()
    expect(emit).toHaveBeenCalledWith('email_verify', { result: 'used' })
  })

  it('offers resend on token_expired', async () => {
    verifyEmail.mockRejectedValue({ status: 410, code: 'token_expired' })
    resendVerification.mockResolvedValue({ status: 'verification_sent' })
    await render()
    const input = tid('verify-email-input')
    expect(input).toBeTruthy()
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, 'a@b.co')
      input.dispatchEvent(new Event('input', { bubbles: true }))
    })
    await act(async () => tid('verify-resend').click())
    expect(resendVerification).toHaveBeenCalledWith('a@b.co')
    expect(tid('verify-resent')).toBeTruthy()
  })

  it('explains email_changed with a resend form', async () => {
    verifyEmail.mockRejectedValue({ status: 409, code: 'email_changed' })
    await render()
    expect(tid('verify-expired').textContent).toMatch(/email address changed/i)
    expect(tid('verify-email-input')).toBeTruthy()
    expect(emit).toHaveBeenCalledWith('email_verify', { result: 'email_changed' })
  })

  it('links to sign-up on token_invalid', async () => {
    verifyEmail.mockRejectedValue({ status: 400, code: 'token_invalid' })
    await render()
    expect(tid('verify-signup-link').getAttribute('href')).toBe('/signup')
  })
})
