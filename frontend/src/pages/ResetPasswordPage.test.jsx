// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom'

const api = vi.hoisted(() => ({ confirmPasswordReset: vi.fn() }))
const auth = vi.hoisted(() => ({ applySession: vi.fn(async () => ({})) }))
vi.mock('../services/authApi', () => api)
vi.mock('../telemetry/client', () => ({ emit: vi.fn() }))
vi.mock('../context/AuthContext', () => ({ useAuth: () => auth }))

import ResetPasswordPage from './ResetPasswordPage'
import { emit } from '../telemetry/client'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
let container, root, location
function Where() { location = useLocation(); return <p data-tid="where">home</p> }
const setValue = (input, value) => {
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, value)
  input.dispatchEvent(new Event('input', { bubbles: true }))
}
const mount = async (path = '/reset-password?token=tok123') => {
  window.history.replaceState(null, '', path)
  await act(async () => root.render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/reset-password" element={<ResetPasswordPage />} />
        <Route path="*" element={<Where />} />
      </Routes>
    </MemoryRouter>))
}
const fill = (pw, confirm) => act(() => {
  setValue(container.querySelector('[data-tid="reset.password"]'), pw)
  setValue(container.querySelector('[data-tid="reset.confirm"]'), confirm)
})
const submit = () => act(async () => container.querySelector('form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })))

beforeEach(() => {
  api.confirmPasswordReset.mockReset()
  auth.applySession.mockClear()
  emit.mockClear()
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})
afterEach(() => { act(() => root.unmount()); container.remove() })

describe('ResetPasswordPage', () => {
  it('strips the token from the address bar', async () => {
    await mount()
    expect(window.location.search).toBe('')
  })

  it('blocks submit when the confirmation differs', async () => {
    await mount()
    fill('a-long-passphrase-1', 'different')
    expect(container.querySelector('[data-tid="reset.mismatch"]')).not.toBeNull()
    expect(container.querySelector('[data-tid="reset.submit"]').disabled).toBe(true)
    await submit()
    expect(api.confirmPasswordReset).not.toHaveBeenCalled()
  })

  it('shows password_common under the field', async () => {
    api.confirmPasswordReset.mockRejectedValueOnce({ status: 422, code: 'password_common', detail: '' })
    await mount()
    fill('password1234', 'password1234')
    await submit()
    const field = container.querySelector('[data-tid="reset.password-error"]')
    expect(field.textContent).toMatch(/too common/)
    expect(container.querySelector('[data-tid="reset.error"]')).toBeNull()
  })

  it('applies the session and goes home with the notice', async () => {
    api.confirmPasswordReset.mockResolvedValueOnce({ status: 'password_reset', session: { access_token: 'a' } })
    await mount()
    fill('a-long-passphrase-1', 'a-long-passphrase-1')
    await submit()
    expect(api.confirmPasswordReset).toHaveBeenCalledWith('tok123', 'a-long-passphrase-1')
    expect(auth.applySession).toHaveBeenCalledWith({ access_token: 'a' })
    expect(location.pathname).toBe('/')
    expect(location.state.message).toBe('Password changed — other devices were signed out')
    expect(emit).toHaveBeenCalledWith('password_reset', { step: 'confirm', result: 'ok' })
  })

  it.each([['token_expired', 'expired'], ['token_used', 'used'], ['token_invalid', 'invalid']])(
    '%s links back to /forgot-password', async (code, result) => {
      api.confirmPasswordReset.mockRejectedValueOnce({ status: 410, code, detail: '' })
      await mount()
      fill('a-long-passphrase-1', 'a-long-passphrase-1')
      await submit()
      expect(container.querySelector('[data-tid="reset.request-new"]').getAttribute('href')).toBe('/forgot-password')
      expect(emit).toHaveBeenCalledWith('password_reset', { step: 'confirm', result })
    })

  it('offers a new link when the token is missing', async () => {
    await mount('/reset-password')
    expect(container.querySelector('[data-tid="reset.request-new"]')).not.toBeNull()
    expect(container.querySelector('form')).toBeNull()
  })
})
