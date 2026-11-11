// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom'

const auth = { login: vi.fn(async () => { auth.isAuthenticated = true; return {} }), isAuthenticated: false, loading: false, requiresPasswordChange: false }
vi.mock('../context/AuthContext', () => ({ useAuth: () => auth }))

const clientConfig = { value: {} }
vi.mock('../hooks/useClientConfig', async (orig) => ({
  ...(await orig()),
  useClientConfig: () => ({ config: clientConfig.value, loaded: true }),
}))
const resendVerification = vi.fn(async () => ({ status: 'verification_sent' }))
vi.mock('../services/authApi', () => ({ resendVerification: (...a) => resendVerification(...a) }))

import LoginPage from './LoginPage'
import { RequireAuth } from '../App'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

let container, root, location
function Where() { location = useLocation(); return <p>page</p> }
const setValue = (input, value) => {
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, value)
  input.dispatchEvent(new Event('input', { bubbles: true }))
}
const render = async (path) => act(async () => root.render(
  <MemoryRouter initialEntries={[path]}>
    <Routes>
      <Route path="/login" element={<><LoginPage /><Where /></>} />
      <Route path="*" element={<RequireAuth><Where /></RequireAuth>} />
    </Routes>
  </MemoryRouter>,
))
const signIn = async () => {
  const [user, pw] = container.querySelectorAll('input')
  act(() => { setValue(user, 'u'); setValue(pw, 'secret-pass') })
  await act(async () => container.querySelector('form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })))
}

beforeEach(() => {
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  auth.isAuthenticated = false
  clientConfig.value = {}
  resendVerification.mockClear()
})
afterEach(() => { act(() => root.unmount()); container.remove() })

describe('sign-in return path', () => {
  it('sends a signed-out deep link to login with the page kept in ?next=', async () => {
    await render('/alerts?watch=1&replan=1')
    expect(location.pathname).toBe('/login')
    expect(new URLSearchParams(location.search).get('next')).toBe('/alerts?watch=1&replan=1')
  })

  it('returns to the intended page after signing in', async () => {
    await render('/login?next=%2Falerts%3Fwatch%3D1%26replan%3D1')
    await signIn()
    expect(location.pathname + location.search).toBe('/alerts?watch=1&replan=1')
  })

  it('never follows an off-site next', async () => {
    await render('/login?next=https%3A%2F%2Fevil.example%2F')
    await signIn()
    expect(location.pathname).toBe('/')
  })
})

describe('privacy choices on the login page', () => {
  it('offers the footer "Privacy choices" button to signed-out visitors', async () => {
    await render('/login')
    expect(container.querySelector('[data-tid="privacy.choices"]')).not.toBeNull()
  })
})

describe('account links on the login page', () => {
  const tid = (id) => container.querySelector(`[data-tid="${id}"]`)

  it('hides Create account and Forgot password against a backend with no auth config', async () => {
    await render('/login')
    expect(tid('login.create-account')).toBeNull()
    expect(tid('login.forgot')).toBeNull()
    expect(container.textContent).toContain('Username')
    expect(container.textContent).not.toContain('Username or email')
  })

  it('shows the links and the email-aware label when the config enables them', async () => {
    clientConfig.value = { auth: { signup_available: true, password_reset_available: true } }
    await render('/login')
    expect(tid('login.create-account').getAttribute('href')).toBe('/signup')
    expect(tid('login.forgot').getAttribute('href')).toBe('/forgot-password')
    expect(container.textContent).toContain('Username or email')
  })

  it('shows the email hint and a working resend on account_pending', async () => {
    const err = Object.assign(new Error('pending'), { code: 'account_pending', extra: { email_hint: 'j•••@example.com' } })
    auth.login.mockRejectedValueOnce(err)
    await render('/login')
    const [user, pw] = container.querySelectorAll('input')
    act(() => { setValue(user, 'jane@example.com'); setValue(pw, 'secret-pass') })
    await act(async () => container.querySelector('form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })))
    expect(tid('login.pending').textContent).toContain('j•••@example.com')
    await act(async () => { tid('login.resend').dispatchEvent(new MouseEvent('click', { bubbles: true })) })
    expect(resendVerification).toHaveBeenCalledWith('jane@example.com')
    expect(tid('login.resent')).not.toBeNull()
  })
})
