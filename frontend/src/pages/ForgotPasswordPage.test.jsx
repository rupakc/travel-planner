// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'

const api = vi.hoisted(() => ({ requestPasswordReset: vi.fn() }))
vi.mock('../services/authApi', () => api)
vi.mock('../telemetry/client', () => ({ emit: vi.fn() }))
vi.mock('../hooks/useClientConfig', () => ({
  useClientConfig: () => ({ config: { auth: { password_reset_available: true } }, loaded: true }),
  resetAvailable: () => true,
}))

import ForgotPasswordPage from './ForgotPasswordPage'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
let container, root
const setValue = (input, value) => {
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, value)
  input.dispatchEvent(new Event('input', { bubbles: true }))
}
const submit = async (email) => {
  act(() => setValue(container.querySelector('input'), email))
  await act(async () => container.querySelector('form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })))
}
beforeEach(async () => {
  api.requestPasswordReset.mockReset()
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  await act(async () => root.render(<MemoryRouter><ForgotPasswordPage /></MemoryRouter>))
})
afterEach(() => { act(() => root.unmount()); container.remove() })

describe('ForgotPasswordPage', () => {
  it('shows identical text for 202 and for an unexpected failure', async () => {
    api.requestPasswordReset.mockResolvedValueOnce({ status: 'reset_sent' })
    await submit('known@example.com')
    const first = container.querySelector('[data-tid="forgot.sent"]').textContent
    expect(first).toMatch(/If an account uses that email, a link is on its way/)
    expect(api.requestPasswordReset).toHaveBeenCalledWith('known@example.com')

    act(() => root.unmount()); root = createRoot(container)
    api.requestPasswordReset.mockRejectedValueOnce({ status: 404, code: null, detail: 'x' })
    await act(async () => root.render(<MemoryRouter><ForgotPasswordPage /></MemoryRouter>))
    await submit('unknown@example.com')
    expect(container.querySelector('[data-tid="forgot.sent"]').textContent).toBe(first)
  })

  it('shows rate-limit and email-unavailable errors instead', async () => {
    api.requestPasswordReset.mockRejectedValueOnce({ status: 429, code: 'rate_limited', detail: '' })
    await submit('a@example.com')
    expect(container.querySelector('[data-tid="forgot.error"]').textContent).toMatch(/Too many attempts/)
    expect(container.querySelector('[data-tid="forgot.sent"]')).toBeNull()
    api.requestPasswordReset.mockRejectedValueOnce({ status: 503, code: 'email_unavailable', detail: '' })
    await submit('a@example.com')
    expect(container.querySelector('[data-tid="forgot.error"]').textContent).toMatch(/Email isn't available/)
  })

  it('a network failure (status 0) is an error, not "on its way"', async () => {
    api.requestPasswordReset.mockRejectedValueOnce({ status: 0, code: null, detail: 'Network Error' })
    await submit('a@example.com')
    expect(container.querySelector('[data-tid="forgot.sent"]')).toBeNull()
    expect(container.querySelector('[data-tid="forgot.error"]').textContent).toBe('Something went wrong. Please try again.')
  })
})
