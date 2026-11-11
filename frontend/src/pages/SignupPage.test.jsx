// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom'

const auth = { isAuthenticated: false }
vi.mock('../context/AuthContext', () => ({ useAuth: () => auth }))
const clientConfig = { value: {} }
vi.mock('../hooks/useClientConfig', async (orig) => ({
  ...(await orig()),
  useClientConfig: () => ({ config: clientConfig.value, loaded: true }),
}))
const signup = vi.fn()
vi.mock('../services/authApi', () => ({ signup: (...a) => signup(...a) }))
vi.mock('../services/api', () => ({ getAuthProviders: async () => [] }))
const emit = vi.fn()
vi.mock('../telemetry/client', () => ({ emit: (...a) => emit(...a) }))

import SignupPage from './SignupPage'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

let container, root, location
function Where() { location = useLocation(); return <p>elsewhere</p> }
const tid = (id) => container.querySelector(`[data-tid="${id}"]`)
const setValue = (input, value) => {
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, value)
  input.dispatchEvent(new Event('input', { bubbles: true }))
}
const render = async () => act(async () => root.render(
  <MemoryRouter initialEntries={['/signup']}>
    <Routes>
      <Route path="/signup" element={<SignupPage />} />
      <Route path="*" element={<Where />} />
    </Routes>
  </MemoryRouter>,
))
const fill = () => act(() => {
  setValue(tid('signup.username'), 'Wander_42')
  setValue(tid('signup.email'), 'Wander@Example.com')
  setValue(tid('signup.password'), 'correct horse battery')
})
const submit = () => act(async () => tid('signup.submit').closest('form')
  .dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })))

beforeEach(() => {
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  auth.isAuthenticated = false
  location = undefined
  clientConfig.value = { auth: { signup_available: true, signup_mode: 'open' } }
  signup.mockReset(); emit.mockReset()
})
afterEach(() => { act(() => root.unmount()); container.remove() })

describe('SignupPage', () => {
  it('lower-cases the username as typed and submits to signup, then goes to check-email', async () => {
    signup.mockResolvedValue({ status: 'verification_sent', email: 'wander@example.com', expires_in: 1800 })
    await render()
    await fill()
    expect(tid('signup.username').value).toBe('wander_42')
    await submit()
    expect(signup).toHaveBeenCalledWith({
      username: 'wander_42', email: 'Wander@Example.com', password: 'correct horse battery',
    })
    expect(location.pathname).toBe('/check-email')
    expect(location.search).toBe('')
    expect(location.state).toEqual({ email: 'wander@example.com' })
    expect(emit).toHaveBeenCalledWith('auth_start', { method: 'password', mode: 'signup' })
    expect(emit).toHaveBeenCalledWith('signup_step', { step: 'check_email' })
  })

  it('shows 409 username_taken under the username field', async () => {
    signup.mockRejectedValue({ status: 409, code: 'username_taken', detail: 'taken', extra: {} })
    await render()
    await fill()
    await submit()
    expect(tid('signup.username-error').textContent).toBe('That username is taken.')
    expect(tid('signup.error')).toBeNull()
    expect(location).toBeUndefined()
  })

  it('shows password errors under the password field and unknown ones as a form error', async () => {
    signup.mockRejectedValueOnce({ status: 422, code: 'password_common', detail: '', extra: {} })
    await render()
    await fill()
    await submit()
    expect(tid('signup.password-error').textContent).toContain('too common')
    signup.mockRejectedValueOnce({ status: 503, code: 'email_unavailable', detail: '', extra: {} })
    await submit()
    expect(tid('signup.error').textContent).toContain("Email isn't available")
  })

  it('hides the invite field in open mode and shows it in invite mode', async () => {
    await render()
    expect(tid('signup.invite')).toBeNull()
    clientConfig.value = { auth: { signup_available: true, signup_mode: 'invite' } }
    await render()
    expect(tid('signup.invite')).not.toBeNull()
  })

  it('sends the invite code and display name when given', async () => {
    clientConfig.value = { auth: { signup_available: true, signup_mode: 'invite' } }
    signup.mockResolvedValue({ status: 'verification_sent', email: 'a@b.co' })
    await render()
    await fill()
    act(() => { setValue(tid('signup.invite'), ' CODE1 '); setValue(tid('signup.display-name'), 'Wan') })
    await submit()
    expect(signup).toHaveBeenCalledWith(expect.objectContaining({ invite_code: 'CODE1', display_name: 'Wan' }))
  })

  it('rejects an invalid username locally without calling the API', async () => {
    await render()
    act(() => { setValue(tid('signup.username'), 'a!'); setValue(tid('signup.email'), 'a@b.co'); setValue(tid('signup.password'), 'x') })
    await submit()
    expect(signup).not.toHaveBeenCalled()
    expect(tid('signup.username-error')).not.toBeNull()
  })

  it('renders the strength meter once a password is typed', async () => {
    await render()
    expect(tid('signup.strength')).toBeNull()
    await fill()
    expect(Number(tid('signup.strength').dataset.score)).toBeGreaterThanOrEqual(3)
  })

  it('goes to /login when sign-up is not available', async () => {
    clientConfig.value = {}
    await render()
    expect(location.pathname).toBe('/login')
  })
})
